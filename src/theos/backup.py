"""Create or restore a consistent archive while the application is stopped."""

import argparse
import fcntl
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path


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
    parser.add_argument("action", choices=("create", "restore"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.action == "create":
        backup(args.directory, args.archive)
    else:
        restore(args.archive, args.directory)


if __name__ == "__main__":
    main()
