"""Replace a single-worker deployment, restoring its previous image and volume on failure."""

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
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
        self.history_path = self.directory / "release-history.json"

    def retain_releases(self, candidate, previous, prior_result):
        """Keep three verified successful releases; leave untracked data alone."""

        def valid(release):
            if not isinstance(release, dict):
                return False
            revision = release.get("revision", "")
            volume = release.get("volume", "")
            return (
                isinstance(revision, str)
                and re.fullmatch(r"[a-f0-9]{40}", revision) is not None
                and isinstance(volume, str)
                and re.fullmatch(
                    re.escape(self.project_name) + r"-rpi-" + revision[:12] + r"-[a-f0-9]{8}",
                    volume,
                )
                is not None
                and isinstance(release.get("tag"), str)
                and re.fullmatch(r"rpi-v\d+\.\d+\.\d+", release["tag"]) is not None
            )

        if not valid(candidate) or (previous and not valid(previous)):
            raise DeploymentError("Release retention skipped: invalid release metadata.")
        if self.history_path.exists():
            history = json.loads(self.history_path.read_text())
            if (
                not isinstance(history, list)
                or not all(valid(item) for item in history)
                or len({item["volume"] for item in history}) != len(history)
                or (previous and (not history or history[-1]["volume"] != previous["volume"]))
                or (not previous and history)
                or any(item["volume"] == candidate["volume"] for item in history)
            ):
                raise DeploymentError("Release retention skipped: inconsistent release history.")
        else:
            history = []
            if (
                previous
                and isinstance(prior_result, dict)
                and prior_result.get("status") == "deployed"
                and prior_result.get("current") == previous
                and valid(prior_result.get("previous"))
                and prior_result["previous"]["volume"] != previous["volume"]
            ):
                history.append(prior_result["previous"])
            if previous:
                history.append(previous)
        if previous and candidate["volume"] == previous["volume"]:
            raise DeploymentError("Release retention skipped: duplicate release volume.")
        history.append(candidate)
        # Persist before removing anything, so a crash never loses the protected set.
        write_json(self.history_path, history)
        protected = {item["volume"] for item in history[-3:]}
        remaining = []
        existing = set(self.docker("volume", "ls", "-q").splitlines())
        for release in history[:-3]:
            volume = release["volume"]
            if volume in protected:
                remaining.append(release)
                continue
            if volume in existing:
                # Do not remove a volume used by any container, even a stopped one.
                if self.docker("ps", "-aq", "--filter", f"volume={volume}"):
                    remaining.append(release)
                    continue
                self.docker("volume", "rm", volume)
        write_json(self.history_path, remaining + history[-3:])
        return remaining

    def docker(self, *args, timeout=300):
        try:
            return subprocess.run(
                ["docker", *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise DeploymentError(f"Docker command failed: {' '.join(args[:3])}") from error

    def compose(self, release, *args):
        environment = dict(
            os.environ,
            AGENT_IMAGE=release["image"],
            AGENT_DATA_VOLUME=release["volume"],
            AGENT_WEB_IMAGE=release.get("web_image", "theos-web:local"),
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
        ]
        # Host-installed skills stay shared across releases and rollback.
        skills_compose = self.directory / "compose.skills.yaml"
        if skills_compose.is_file():
            command.extend(["-f", str(skills_compose)])
        command.extend(args)
        try:
            return subprocess.run(
                command, env=environment, check=True, capture_output=True, text=True, timeout=300
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise DeploymentError(f"Compose command failed: {' '.join(args)}") from error

    @staticmethod
    def services(release):
        return ("theos", "web") if release.get("web_image") else ("theos",)

    def healthy(self, release):
        deadline = time.monotonic() + self.health_timeout
        while time.monotonic() < deadline:
            healthy = True
            for service in self.services(release):
                container = self.compose(release, "ps", "-q", service)
                if not container:
                    healthy = False
                    continue
                state = json.loads(self.docker("inspect", container))[0]["State"]
                if state.get("Status") in {"exited", "dead"}:
                    raise DeploymentError(f"The {service} service stopped before readiness.")
                healthy = healthy and state.get("Health", {}).get("Status") == "healthy"
            if healthy:
                return
            time.sleep(2)
        raise DeploymentError("Application readiness did not pass before the deadline.")

    def telegram_ready(self, release, *, preflight=False):
        # A one-off checker starts no worker and never opens the application database.
        command = ("run", "--rm", "--no-deps", "-T") if preflight else ("exec", "-T")
        # Compose creates nested mount points inside /data. Keep them out of the
        # candidate volume, which must remain empty until backup restoration.
        check_release = (
            {**release, "volume": release["volume"] + "-preflight"} if preflight else release
        )
        if preflight:
            self.docker("volume", "create", check_release["volume"])
        try:
            try:
                output = self.compose(
                    check_release,
                    *command,
                    "theos",
                    "python",
                    "-m",
                    "theos.operations.telegram_check",
                )
            except DeploymentError:
                raise DeploymentError(
                    "Telegram connection check failed. Verify the bot token, outbound HTTPS, and webhook configuration."
                ) from None
        finally:
            if preflight:
                self.docker("volume", "rm", check_release["volume"])
        if output:
            print(output)

    def restore_previous(self, candidate, previous):
        self.compose(candidate, "stop", *self.services(candidate))
        for kind in ("backup", "restore", "archive"):
            self.remove_helper(f"theos-{kind}-{candidate['revision'][:12]}")
        if previous:
            self.compose(
                previous, "up", "--no-build", "--pull", "never", "-d", *self.services(previous)
            )
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

    def remove_helper(self, name):
        container = self.docker("ps", "-aq", "--filter", f"name=^/{name}$")
        if container:
            try:
                self.docker("rm", "-f", container)
            except DeploymentError:
                # The --rm process can finish between the lookup and removal.
                if self.docker("ps", "-aq", "--filter", f"id={container}"):
                    raise

    def run_helper(self, name, *args, timeout):
        """Remove an interrupted helper before rollback reopens the data volume."""
        try:
            return self.docker(
                "run",
                "--rm",
                "--name",
                name,
                "--no-healthcheck",
                "--label",
                "theos.deployment-helper=true",
                *args,
                timeout=timeout,
            )
        finally:
            self.remove_helper(name)

    def snapshot(self, previous, candidate):
        # Compose resolves quoting and interpolation. Docker's raw env-file parser
        # does not. Give helpers only resolved storage fields, never unrelated settings.
        config = json.loads(self.compose(previous, "config", "--format", "json"))
        environment = config["services"]["theos"].get("environment") or {}
        with tempfile.NamedTemporaryFile(
            mode="w", prefix=".backup-storage-", dir=self.directory, encoding="utf-8"
        ) as private:
            for field in ("ENDPOINT", "BUCKET", "ACCESS_KEY", "SECRET_KEY"):
                name = "AGENT_STORAGE__" + field
                value = environment.get(name)
                if value is None:
                    continue
                if not isinstance(value, str) or "\n" in value or "\r" in value:
                    raise DeploymentError(
                        "Backup storage settings must contain single-line values."
                    )
                private.write(f"{name}={value}\n")
            private.flush()
            return self.snapshot_with_environment(previous, candidate, private.name)

    def snapshot_with_environment(self, previous, candidate, environment_file):
        archive = f"/data/backups/{candidate['tag']}-{candidate['revision'][:12]}.tar.gz"
        self.run_helper(
            f"theos-backup-{candidate['revision'][:12]}",
            "--env-file",
            environment_file,
            "--read-only",
            "--tmpfs",
            "/tmp",
            "-v",
            f"{previous['volume']}:/data",
            candidate["image"],
            "python",
            "-m",
            "theos.backup",
            "create",
            "/data",
            archive,
            timeout=1800,
        )
        # Restore with the old code; only the candidate runs new migrations.
        restore_code = (
            "import os; from pathlib import Path; from theos.backup import restore; "
            f'restore(Path({archive.replace("/data/", "/previous/", 1)!r}),Path("/restore")); '
            'os.chown("/restore",10001,10001); '
            '[os.chown(p,10001,10001) for p in Path("/restore").rglob("*")]'
        )
        self.run_helper(
            f"theos-restore-{candidate['revision'][:12]}",
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
            timeout=900,
        )
        # The candidate understands remote archives. Older release images still create
        # and restore their original archive format before this optional transfer.
        stored = self.run_helper(
            f"theos-archive-{candidate['revision'][:12]}",
            "--env-file",
            environment_file,
            "--read-only",
            "--tmpfs",
            "/tmp",
            "-v",
            f"{previous['volume']}:/data",
            candidate["image"],
            "python",
            "-m",
            "theos.backup",
            "archive",
            "/data",
            archive,
            timeout=1800,
        )
        return (
            stored.strip()
            if stored.strip().startswith("r2:")
            else f"{previous['volume']}:{archive}"
        )

    def deploy(self, image, tag, revision, web_image=None):
        if not re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}", image):
            raise DeploymentError("Use an immutable GHCR image digest.")
        if not re.fullmatch(r"rpi-v\d+\.\d+\.\d+", tag) or not re.fullmatch(
            r"[a-f0-9]{40}", revision
        ):
            raise DeploymentError("Invalid release tag or commit revision.")
        if web_image and not re.fullmatch(
            r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}", web_image
        ):
            raise DeploymentError("Use an immutable GHCR frontend image digest.")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        environment = self.directory / ".env"
        if not environment.is_file():
            raise DeploymentError(f"Configure the private environment file at {environment}.")
        environment.chmod(0o600)
        with (self.directory / "deploy.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.deploy_locked(image, tag, revision, web_image)

    def deploy_locked(self, image, tag, revision, web_image=None):
        self.recover_interrupted()
        previous = json.loads(self.current_path.read_text()) if self.current_path.exists() else None
        try:
            prior_result = (
                json.loads(self.result_path.read_text()) if self.result_path.exists() else None
            )
        except (OSError, ValueError):
            prior_result = None
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
        if (
            previous
            and previous["image"] == image
            and previous["revision"] == revision
            and previous.get("web_image") == web_image
        ):
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
        if web_image:
            candidate["web_image"] = web_image
        result = dict(status="failed", candidate=candidate, previous=previous, backup=None)
        changing = False
        try:
            # Pull and validate configuration while the previous service stays available.
            self.docker("pull", image)
            if web_image:
                self.docker("pull", web_image)
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
                self.compose(previous, "stop", *self.services(previous))
                result["backup"] = self.snapshot(previous, candidate)
            self.compose(
                candidate, "up", "--no-build", "--pull", "never", "-d", *self.services(candidate)
            )
            self.healthy(candidate)
            self.telegram_ready(candidate)
            write_json(self.current_path, candidate)
            changing = False
            self.pending_path.unlink()
            result.update(status="deployed", current=candidate)
            write_json(self.result_path, result)
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
        try:
            remaining = self.retain_releases(candidate, previous, prior_result)
            if remaining:
                result["retention_warning"] = "Older release volumes are still in use."
                write_json(self.result_path, result)
        except (DeploymentError, OSError, ValueError, TypeError) as error:
            # The new release is already active. Never roll it back for cleanup.
            result["retention_warning"] = str(error)
            write_json(self.result_path, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--web-image", required=True)
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
            args.image, args.tag, args.revision, args.web_image
        )
    except (DeploymentError, BlockingIOError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
