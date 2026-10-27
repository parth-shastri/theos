"""Capture a recoverable Chromium profile without browser cache files.

This standard-library script runs inside the dedicated browser sandbox.
"""

import os
import re
import select
import signal
import subprocess
import tarfile
import time
from contextlib import contextmanager
from pathlib import Path

PROFILE = Path("/tmp/theos-browser/profile")
ARCHIVE = Path("/tmp/theos-browser/profile.tar.gz")
EXCLUDED = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "GrShaderCache",
    "ShaderCache",
    "Crashpad",
    "BrowserMetrics",
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "LOCK",
    "lockfile",
}
LIMIT = 256 * 1024 * 1024


def browser_processes():
    """Find only this profile's browser tree. Never pause the CLI or snapshot process."""
    processes = {}
    if Path("/proc").is_dir():
        for directory in Path("/proc").glob("[0-9]*"):
            try:
                args = directory.joinpath("cmdline").read_bytes().decode().split("\0")
                status = directory.joinpath("status").read_text()
                parent = int(re.search(r"^PPid:\s+(\d+)", status, re.MULTILINE).group(1))
                processes[int(directory.name)] = (parent, args)
            except (OSError, UnicodeError, AttributeError):
                continue
    else:
        output = subprocess.check_output(["ps", "-axo", "pid=,ppid=,command="], text=True)
        for line in output.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3:
                processes[int(parts[0])] = (int(parts[1]), parts[2].split())
    selected = {
        pid
        for pid, (_, args) in processes.items()
        if any(
            arg.startswith("--user-data-dir=")
            and Path(arg.split("=", 1)[1]).resolve() == PROFILE.resolve()
            for arg in args
        )
    }
    while True:
        children = {pid for pid, (parent, _) in processes.items() if parent in selected}
        if children <= selected:
            return selected
        selected |= children


def resume(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass


@contextmanager
def paused_browser():
    # 1. Pipe EOF resumes the browser even if the snapshot process is killed.
    # The independent watchdog also bounds a stuck capture.
    pids = browser_processes()
    if not pids:
        yield
        return
    reader, writer = os.pipe()
    watchdog = os.fork()
    if watchdog == 0:
        # SDK timeouts can terminate an entire command process group.
        os.setsid()
        os.close(writer)
        try:
            select.select([reader], [], [], 25)
            resume(pids)
        finally:
            os._exit(0)
    os.close(reader)
    try:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGSTOP)
            except ProcessLookupError:
                pass
        # 2. Capture each database with its WAL or rollback journal while writers stop.
        # Chromium can recover an interrupted transaction from these files on restore.
        started = time.monotonic()
        yield
        if time.monotonic() - started >= 20:
            raise TimeoutError("The browser profile capture exceeded its deadline.")
    finally:
        resume(pids)
        os.close(writer)
        os.waitpid(watchdog, 0)


def snapshot():
    total = 0
    temporary = ARCHIVE.with_suffix(".pending")
    try:
        with paused_browser(), tarfile.open(temporary, "w:gz", compresslevel=1) as archive:
            for source in PROFILE.rglob("*"):
                relative = source.relative_to(PROFILE)
                if (
                    any(part in EXCLUDED for part in relative.parts)
                    or source.is_symlink()
                    or not source.is_file()
                    or source.name.endswith("-shm")
                ):
                    continue
                total += source.stat().st_size
                if total > LIMIT:
                    raise ValueError("The browser profile exceeds its size limit.")
                archive.add(source, arcname=str(relative), recursive=False)
        temporary.chmod(0o600)
        temporary.replace(ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)


def restore():
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        members = archive.getmembers()
        if sum(member.size for member in members) > LIMIT:
            raise ValueError("The browser profile exceeds its size limit.")
        for member in members:
            path = Path(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or any(part in EXCLUDED for part in path.parts)
            ):
                raise ValueError("The browser profile contains an invalid entry.")
        archive.extractall(PROFILE, members=members, filter="data")


if __name__ == "__main__":
    import sys

    {"snapshot": snapshot, "restore": restore}[sys.argv[1]]()
