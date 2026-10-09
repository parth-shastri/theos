"""Test replacement and data rollback using a disposable Docker project and a local image."""

import argparse
import json
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path

from deploy_rpi import Deployer, DeploymentError


def rehearse(image, compose_file):
    project = f"theos-rehearsal-{uuid.uuid4().hex[:8]}"
    broken_image = f"{project}:broken"
    subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True)
    subprocess.run(
        ["docker", "build", "-t", broken_image, "-"],
        input=f"FROM {image}\nHEALTHCHECK CMD exit 1\n",
        text=True,
        check=True,
        capture_output=True,
    )
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        directory = Path(temporary)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        (directory / ".env").write_text(
            f"AGENT_PROVIDER=fake\nAGENT_USERS={{}}\nHOST_PORT={port}\nHOST_BIND_IP=127.0.0.1\n"
        )
        compose = directory / "compose.yaml"
        compose.write_text(
            compose_file.read_text().replace(
                "    env_file: .env",
                "    healthcheck:\n      interval: 1s\n      start_period: 2s\n"
                "      timeout: 3s\n      retries: 2\n    env_file: .env",
            )
        )

        class RehearsalDeployer(Deployer):
            def docker(self, *args):
                # Both test images already exist locally; production still pulls digest pins.
                if args == ("pull", image) or args == ("pull", broken_image):
                    return ""
                return super().docker(*args)

        deployer = RehearsalDeployer(directory, compose, 30, project_name=project)
        try:
            first = deployer.deploy_locked(image, "rpi-v0.0.1", "a" * 40)["current"]
            seed = (
                'import sqlite3; db=sqlite3.connect("/data/rehearsal.sqlite3"); '
                'db.execute("create table saved(value text)"); '
                'db.execute("insert into saved values (?)",("before-upgrade",)); db.commit()'
            )
            deployer.docker(
                "run", "--rm", "-v", f"{first['volume']}:/data", image, "python", "-c", seed
            )
            second = deployer.deploy_locked(image, "rpi-v0.0.2", "b" * 40)["current"]
            assert second["volume"] != first["volume"]
            try:
                deployer.deploy_locked(broken_image, "rpi-v0.0.3", "c" * 40)
            except DeploymentError:
                result = json.loads(deployer.result_path.read_text())
                assert result["status"] == "rolled_back", result["status"]
            else:
                raise AssertionError("The unhealthy image was accepted")
            assert json.loads(deployer.current_path.read_text()) == second
            verify = (
                'import sqlite3; db=sqlite3.connect("/data/rehearsal.sqlite3"); '
                'assert db.execute("select value from saved").fetchone()[0]=="before-upgrade"'
            )
            for release in [first, second]:
                deployer.docker(
                    "run",
                    "--rm",
                    "-v",
                    f"{release['volume']}:/data:ro",
                    image,
                    "python",
                    "-c",
                    verify,
                )
            deployer.healthy(second)
            print(
                json.dumps(
                    dict(
                        first_install="passed",
                        replacement="passed",
                        rollback="passed",
                        original_database="preserved",
                        restored_database="preserved",
                    ),
                    indent=2,
                )
            )
        finally:
            if deployer.result_path.exists():
                latest = json.loads(deployer.result_path.read_text())
                release = latest.get("candidate") or latest.get("current")
                if release:
                    deployer.compose(release, "down")
            volumes = deployer.docker("volume", "ls", "-q", "--filter", f"name={project}-rpi-")
            for volume in volumes.splitlines():
                if volume.startswith(f"{project}-rpi-"):
                    deployer.docker("volume", "rm", volume)
            deployer.docker("image", "rm", broken_image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="An already-built or pulled Theos image")
    parser.add_argument("--compose-file", type=Path, default=Path("compose.yaml"))
    args = parser.parse_args()
    rehearse(args.image, args.compose_file)


if __name__ == "__main__":
    main()
