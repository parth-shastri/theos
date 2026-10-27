"""Recover the native Mac mini Docker services after login or engine failure."""

import argparse
import fcntl
import json
import logging
import os
import plistlib
import shutil
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

DOCKER = "/Applications/Docker.app/Contents/Resources/bin/docker"
DISK = Path("/Volumes/extssd")
HOME = Path.home()
STATE = HOME / ".local/share/theos-host-guard"
IMAGE = "theos/sandbox-skills:v1.1.0-20261019-18e1cc81d4c3"
PROBE = "theos-host-write-probe"
LABEL = "theos.host-guard=true"
CONTAINERS = (
    "mem0-dev-postgres-1",
    "mem0-dev-mem0-1",
    "mem0-dev-mem0-dashboard-1",
    "theos-voice-whisper-1",
    "theos-voice-kokoro-1",
)
LOGGER = logging.getLogger("theos-host-guard")
AGENT = "com.parthshastri.theos-host-guard"


def install():
    """Install a login agent with an explicit runtime and no shell profile dependency."""
    if sys.platform != "darwin":
        raise SystemExit("Install this guard on the Mac mini.")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = STATE / "guard.py"
    agents = HOME / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / (AGENT + ".plist")
    configuration = {
        "Label": AGENT,
        "ProgramArguments": ["/usr/bin/python3", str(target)],
        "RunAtLoad": True,
        "StartInterval": 60,
        "ProcessType": "Background",
        "ThrottleInterval": 30,
        "WorkingDirectory": str(HOME),
        "StandardErrorPath": str(STATE / "launchd.stderr.log"),
        "StandardOutPath": str(STATE / "launchd.stdout.log"),
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    }
    for path, data in [
        (target, Path(__file__).read_bytes()),
        (plist, plistlib.dumps(configuration)),
    ]:
        if path.exists():
            shutil.copy2(path, path.with_suffix(path.suffix + ".previous"))
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain + "/" + AGENT], capture_output=True)
    subprocess.run(["launchctl", "enable", domain + "/" + AGENT], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print("Installed host recovery agent:", plist)


def command(*args, timeout=25):
    result = subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1000:].strip())
    return result.stdout.strip()


def load_state(path):
    """A damaged recovery journal must not prevent the guard from starting."""
    try:
        state = json.loads(path.read_text())
        if not isinstance(state, dict):
            raise ValueError("Expected recovery state")
        for key in ("failures", "warmup_until", "last_probe", "last_healthy"):
            if key in state and not isinstance(state[key], (int, float)):
                raise ValueError("Invalid recovery counter")
        if not isinstance(state.get("restarts", []), list) or any(
            not isinstance(stamp, (int, float)) for stamp in state.get("restarts", [])
        ):
            raise ValueError("Invalid restart history")
        return state
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        LOGGER.warning("Recovery state is unreadable; checking the host with fresh state")
        return {}


def restart(state, now):
    """Bound recovery attempts. Never erase Docker storage or prune volumes."""
    attempts = [stamp for stamp in state.get("restarts", []) if now - stamp < 3600]
    if attempts and now - attempts[-1] < 900:
        return
    if len(attempts) >= 3:
        LOGGER.error("Docker recovery needs operator attention after three restarts")
        return
    # Persist intent even if the CLI times out after accepting the restart.
    state.update(restarts=[*attempts, now], warmup_until=now + 120, failures=0)
    LOGGER.warning("Restarting Docker Desktop after repeated health failures")
    command("desktop", "restart", "--detach")


def reconcile(state, now):
    # Do not start Docker against a missing external data directory.
    if not DISK.is_mount():
        LOGGER.warning("Waiting for the external SSD")
        return
    if now < state.get("warmup_until", 0):
        return
    try:
        command("info", "--format", "{{.ServerVersion}}")
    except (RuntimeError, subprocess.TimeoutExpired):
        state["failures"] = state.get("failures", 0) + 1
        if state["failures"] == 1:
            LOGGER.warning("Starting Docker Desktop")
            state["warmup_until"] = now + 120
            command("desktop", "start", "--detach")
        else:
            restart(state, now)
        return

    interval = 60 if state.get("failures") else 300
    if now - state.get("last_probe", 0) < interval:
        return
    state["last_probe"] = now
    try:
        # Only remove this guard's stale probe, never an application container.
        stale = command("ps", "-aq", "--filter", "label=" + LABEL)
        if stale:
            command("rm", *stale.split())
        created = command(
            "create",
            "--pull=never",
            "--name",
            PROBE,
            "--label",
            LABEL,
            "--network",
            "none",
            "--entrypoint",
            "/bin/true",
            IMAGE,
        )
        command("rm", created)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        state["failures"] = state.get("failures", 0) + 1
        LOGGER.error("Docker write probe failed: %s", error)
        if state["failures"] >= 2:
            restart(state, now)
        return

    state["failures"] = 0
    # These containers already retain their Compose configuration and volumes.
    # Start stopped instances without replacing images or recreating data.
    rows = command("ps", "-a", "--format", "{{.Names}} {{.State}}")
    existing = dict(row.split(maxsplit=1) for row in rows.splitlines())
    for name in CONTAINERS:
        if name not in existing:
            LOGGER.error("Expected container is missing: %s", name)
        elif existing[name] != "running":
            LOGGER.warning("Starting stopped container: %s", name)
            command("start", name, timeout=60)
    state["last_healthy"] = now
    LOGGER.info("Docker writes and service containers are healthy")


def main():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(STATE / "guard.log", maxBytes=1_048_576, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    with (STATE / "guard.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        path = STATE / "state.json"
        state = load_state(path)
        try:
            reconcile(state, time.time())
        except Exception:
            LOGGER.exception("Host recovery failed")
        finally:
            temporary = STATE / "state.tmp"
            with temporary.open("w") as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Install the native login agent")
    if parser.parse_args().install:
        install()
    else:
        main()
