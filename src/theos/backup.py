"""Create or restore a consistent archive while the application is stopped."""

import argparse
import fcntl
import gzip
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
from pathlib import Path
from uuid import uuid4


def archive_backup(archive: Path):
    """Move a complete backup to R2 after verifying its uploaded bytes."""
    from theos.services.files.catalog import storage_client
    from theos.settings import Settings

    config = Settings(_env_file=None).storage
    if not config.endpoint:
        return str(archive)
    key = "theos/backups/" + uuid4().hex + ".tar.gz"
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    client = storage_client(config)
    try:
        client.upload_file(str(archive), config.bucket, key)
        response = client.get_object(Bucket=config.bucket, Key=key)
        try:
            remote = hashlib.file_digest(response["Body"], "sha256").hexdigest()
        finally:
            response["Body"].close()
        if remote != digest:
            raise ValueError("Remote backup archive checksum mismatch.")
        archive.unlink()
        return "r2:" + key
    finally:
        client.close()


def restore_remote(key: str, directory: Path):
    """Restore an independent R2 archive through temporary local staging."""
    from theos.services.files.catalog import storage_client
    from theos.settings import Settings

    config = Settings(_env_file=None).storage
    directory.parent.mkdir(parents=True, exist_ok=True)
    client = storage_client(config)
    try:
        with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
            archive = Path(temporary) / "backup.tar.gz"
            client.download_file(config.bucket, key, str(archive))
            restore(archive, directory)
    finally:
        client.close()


def hydrate_remote_files(directory, staging):
    """Include remote-only payloads in a stopped application's independent backup."""
    database = staging / "theos.sqlite3"
    if not database.exists():
        return
    from theos.services.files.catalog import Files, storage_client
    from theos.settings import Settings

    client = None
    try:
        with closing(sqlite3.connect(database)) as db:
            db.row_factory = sqlite3.Row
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            rows = []
            if "context_objects" in tables:
                rows += [
                    (dict(row), "checkpoint") for row in db.execute("SELECT * FROM context_objects")
                ]
            if "files" in tables:
                rows += [(dict(row), "file") for row in db.execute("SELECT * FROM files")]

            def fetch(row, kind, target, expected_sha):
                data = Files.remote_bytes(client, config.bucket, row["object_key"])
                if kind == "checkpoint":
                    valid = hashlib.sha256(gzip.decompress(data)).hexdigest() == row["digest"]
                else:
                    valid = len(data) == row["size"] and (
                        expected_sha is None or hashlib.sha256(data).hexdigest() == expected_sha
                    )
                if not valid:
                    raise ValueError("Remote backup file checksum mismatch.")
                return target, data

            pending = set()

            def write_completed():
                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    pending.remove(future)
                    target, data = future.result()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    target.chmod(0o600)

            # Bound concurrent downloads and the number of retained payloads.
            with ThreadPoolExecutor(max_workers=4) as pool:
                for row, kind in rows:
                    relative = Path("checkpoints" if kind == "checkpoint" else "files") / row["id"]
                    target = staging / relative
                    if target.exists():
                        continue
                    if len(row["id"]) != (64 if kind == "checkpoint" else 32) or any(
                        c not in "0123456789abcdef" for c in row["id"]
                    ):
                        raise ValueError("Invalid remote backup file reference.")
                    if not row["object_key"] or (kind == "checkpoint" and row["status"] != "saved"):
                        raise ValueError("A pending backup file is missing from local storage.")
                    if client is None:
                        config = Settings(_env_file=None, data_dir=directory).storage
                        client = storage_client(config)
                    expected_sha = None
                    if kind == "file" and "records" in tables:
                        digest = db.execute(
                            "SELECT value FROM records WHERE owner=? AND kind='file_digest' AND id=?",
                            (row["owner"], row["id"]),
                        ).fetchone()
                        if digest:
                            expected_sha = json.loads(digest[0])["sha256"]
                    pending.add(pool.submit(fetch, row, kind, target, expected_sha))
                    if len(pending) >= 8:
                        write_completed()
                while pending:
                    write_completed()
    finally:
        if client:
            client.close()


def backup(directory: Path, archive: Path):
    """Snapshot SQLite databases through their backup API before archiving files."""
    directory.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with (directory / "process.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Stop the assistant before you create a full backup.") from None
        # Use the persistent volume because container /tmp has a small fixed limit.
        staging_root = directory / "backups"
        staging_root.mkdir(exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
            staging = Path(temporary)
            for source in directory.rglob("*"):
                relative = source.relative_to(directory)
                if relative.parts[0] in {"backups", "logs"} or source.name == "process.lock":
                    continue
                if source.is_symlink():
                    raise ValueError("Remove symbolic links from the data directory before backup.")
                if (
                    not source.is_file()
                    or source.name.endswith(("-wal", "-shm"))
                    or source.resolve() == archive.resolve()
                ):
                    continue
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix == ".sqlite3":
                    with (
                        closing(sqlite3.connect(source)) as origin,
                        closing(sqlite3.connect(target)) as snapshot,
                    ):
                        origin.backup(snapshot)
                else:
                    shutil.copy2(source, target)
            hydrate_remote_files(directory, staging)
            with tarfile.open(archive, "w:gz") as output:
                output.add(staging, arcname="state")
    archive.chmod(0o600)


def restore(archive: Path, directory: Path):
    """Restore into an empty data directory. Never overwrite a working database."""
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Restore into an empty data directory or a new Docker volume.")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                if (
                    not (member.isfile() or member.isdir())
                    or not Path(member.name).parts
                    or Path(member.name).parts[0] != "state"
                ):
                    raise ValueError("The backup contains an unsupported archive entry.")
            source.extractall(temporary, filter="data")
        for item in (Path(temporary) / "state").iterdir():
            shutil.move(str(item), directory / item.name)


def main():
    """Run a stopped-application backup or restore."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "restore", "archive"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.action == "create":
        backup(args.directory, args.archive)
    elif args.action == "archive":
        print(archive_backup(args.archive))
    elif str(args.archive).startswith("r2:"):
        restore_remote(str(args.archive)[3:], args.directory)
    else:
        restore(args.archive, args.directory)


if __name__ == "__main__":
    main()
