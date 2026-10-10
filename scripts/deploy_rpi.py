"""Replace a single-worker deployment, restoring its previous image and volume on failure."""

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


class DeploymentError(RuntimeError):
    """A release could not be activated safely."""


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


class Deployer:
    def __init__(self, directory, compose_file, health_timeout=120, project_name="theos"):
        self.directory = directory.resolve()
        self.compose_file = compose_file.resolve()
        self.health_timeout = health_timeout
        self.project_name = project_name
        self.current_path = self.directory / "current.json"
        self.pending_path = self.directory / "pending.json"
        self.result_path = self.directory / "deployment-result.json"

    def docker(self, *args):
        try:
            return subprocess.run(
                ["docker", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise DeploymentError(f"Docker command failed: {' '.join(args[:3])}") from error

    def compose(self, release, *args):
        environment = dict(
            os.environ, AGENT_IMAGE=release["image"], AGENT_DATA_VOLUME=release["volume"]
        )
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project_name,
            "--project-directory",
            str(self.directory),
            "--env-file",
            str(self.directory / ".env"),
            "-f",
            release["compose_file"],
            *args,
        ]
        try:
            return subprocess.run(
                command, env=environment, check=True, capture_output=True, text=True, timeout=300
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise DeploymentError(f"Compose command failed: {' '.join(args)}") from error

    def healthy(self, release):
        deadline = time.monotonic() + self.health_timeout
        while time.monotonic() < deadline:
            container = self.compose(release, "ps", "-q", "theos")
            if container:
                raw = self.docker("inspect", container)
                state = json.loads(raw)[0]["State"]
                if state.get("Health", {}).get("Status") == "healthy":
                    return
                if state.get("Status") in {"exited", "dead"}:
                    break
            time.sleep(2)
        raise DeploymentError("Application readiness did not pass before the deadline.")

    def telegram_ready(self, release, *, preflight=False):
        # A one-off checker starts no worker and never opens the application database.
        command = ("run", "--rm", "--no-deps", "-T") if preflight else ("exec", "-T")
        try:
            output = self.compose(
                release, *command, "theos", "python", "-m", "theos.operations.telegram_check"
            )
        except DeploymentError:
            raise DeploymentError(
                "Telegram connection check failed. Verify the bot token, outbound HTTPS, and webhook configuration."
            ) from None
        if output:
            print(output)

    def restore_previous(self, candidate, previous):
        self.compose(candidate, "stop", "theos")
        if previous:
            self.compose(previous, "up", "--no-build", "--pull", "never", "-d", "theos")
            self.healthy(previous)
        self.pending_path.unlink(missing_ok=True)

    def recover_interrupted(self):
        if not self.pending_path.exists():
            return
        pending = json.loads(self.pending_path.read_text())
        current = json.loads(self.current_path.read_text()) if self.current_path.exists() else None
        # A completed commit followed by a crash only needs journal cleanup.
        if current == pending["candidate"]:
            self.pending_path.unlink()
            return
        self.restore_previous(pending["candidate"], pending["previous"])

    def snapshot(self, previous, candidate):
        archive = f"/data/backups/{candidate['tag']}-{candidate['revision'][:12]}.tar.gz"
        self.docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "-v",
            f"{previous['volume']}:/data",
            previous["image"],
            "python",
            "-m",
            "theos.backup",
            "create",
            "/data",
            archive,
        )
        # Restore with the old code; only the candidate runs new migrations.
        restore_code = (
            "import os; from pathlib import Path; from theos.backup import restore; "
            f'restore(Path({archive.replace("/data/", "/previous/", 1)!r}),Path("/restore")); '
            'os.chown("/restore",10001,10001); '
            '[os.chown(p,10001,10001) for p in Path("/restore").rglob("*")]'
        )
        self.docker(
            "run",
            "--rm",
            "--user",
            "0",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "-v",
            f"{previous['volume']}:/previous:ro",
            "-v",
            f"{candidate['volume']}:/restore",
            previous["image"],
            "python",
            "-c",
            restore_code,
        )
        return f"{previous['volume']}:{archive}"

    def deploy(self, image, tag, revision):
        if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}", image):
            raise DeploymentError("Use an immutable GHCR image digest.")
        if not re.fullmatch(r"rpi-v\d+\.\d+\.\d+", tag) or not re.fullmatch(
            r"[a-f0-9]{40}", revision
        ):
            raise DeploymentError("Invalid release tag or commit revision.")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        environment = self.directory / ".env"
        if not environment.is_file():
            raise DeploymentError(f"Configure the private environment file at {environment}.")
        environment.chmod(0o600)
        with (self.directory / "deploy.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.deploy_locked(image, tag, revision)

    def deploy_locked(self, image, tag, revision):
        self.recover_interrupted()
        previous = json.loads(self.current_path.read_text()) if self.current_path.exists() else None
        existing = self.docker(
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={self.project_name}",
            "--filter",
            "label=com.docker.compose.service=theos",
        )
        if existing and not previous:
            raise DeploymentError("An unmanaged Theos service exists. Adopt it before deployment.")
        if previous and previous["image"] == image and previous["revision"] == revision:
            self.healthy(previous)
            self.telegram_ready(previous)
            result = dict(status="already_deployed", current=previous)
            write_json(self.result_path, result)
            return result
        release_dir = self.directory / "releases" / tag
        release_dir.mkdir(parents=True, exist_ok=True)
        release_compose = release_dir / "compose.yaml"
        if release_compose.exists():
            raise DeploymentError("This release was already attempted. Use a new release tag.")
        shutil.copyfile(self.compose_file, release_compose)
        candidate = dict(
            image=image,
            tag=tag,
            revision=revision,
            compose_file=str(release_compose),
            volume=f"{self.project_name}-rpi-{revision[:12]}-{uuid.uuid4().hex[:8]}",
            activated_at=datetime.now(UTC).isoformat(),
        )
        result = dict(status="failed", candidate=candidate, previous=previous, backup=None)
        changing = False
        try:
            # Pull and validate configuration while the previous service stays available.
            self.docker("pull", image)
            self.compose(candidate, "config", "--quiet")
            self.docker("volume", "create", candidate["volume"])
            self.docker(
                "run",
                "--rm",
                "--user",
                "0",
                "--network",
                "none",
                "--read-only",
                "-v",
                f"{candidate['volume']}:/data",
                image,
                "python",
                "-c",
                'import os; os.chown("/data",10001,10001)',
            )
            # Reject invalid Telegram settings before stopping the current worker.
            self.telegram_ready(candidate, preflight=True)
            write_json(self.pending_path, dict(candidate=candidate, previous=previous))
            changing = True
            if previous:
                self.compose(previous, "stop", "theos")
                result["backup"] = self.snapshot(previous, candidate)
            self.compose(candidate, "up", "--no-build", "--pull", "never", "-d", "theos")
            self.healthy(candidate)
            self.telegram_ready(candidate)
            write_json(self.current_path, candidate)
            changing = False
            self.pending_path.unlink()
            result.update(status="deployed", current=candidate)
            write_json(self.result_path, result)
            return result
        except BaseException as error:
            result["error"] = str(error)
            if changing:
                try:
                    self.restore_previous(candidate, previous)
                    result.update(status="rolled_back" if previous else "failed", current=previous)
                except BaseException as rollback_error:
                    result.update(status="rollback_failed", rollback_error=str(rollback_error))
            write_json(self.result_path, result)
            raise DeploymentError(
                f"Release failed; status={result['status']}. See {self.result_path}."
            ) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--deploy-dir", type=Path, default=Path.home() / "theos-deploy")
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise DeploymentError(f"Deployment interrupted by signal {signum}.")

    signal.signal(signal.SIGTERM, interrupted)
    try:
        result = Deployer(args.deploy_dir, args.compose_file).deploy(
            args.image, args.tag, args.revision
        )
    except (DeploymentError, BlockingIOError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
