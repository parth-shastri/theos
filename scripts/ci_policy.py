"""Select container coverage for the destination branch and changed build files."""

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path

STANDARD = ["amd64", "arm64", "386", "armv7", "ppc64le"]
EXTENDED = [*STANDARD, "s390x", "riscv64"]
BUILD_PATHS = (
    "Dockerfile*",
    "**/Dockerfile*",
    ".dockerignore",
    "compose*.yaml",
    "pyproject.toml",
    "uv.lock",
    "web/*",
    "web/**",
    ".github/workflows/*",
    ".github/actionlint.yaml",
    "scripts/ci_policy.py",
    "scripts/install_ci_tools.sh",
    "scripts/check_release.py",
    "scripts/deploy_rpi.py",
    "scripts/rehearse_rpi.py",
    "scripts/theos_smoke.py",
    "tests/deployment/*",
)


def changed_paths(event_name: str, event: dict, root: Path) -> list[str] | None:
    # Compare the PR changes, or all commits in an integration-branch push.
    if event_name == "pull_request":
        base = event["pull_request"]["base"]["sha"]
        head = event["pull_request"]["head"]["sha"]
        separator = "..."
    else:
        base, head = event["before"], event["after"]
        separator = ".."
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) and int(sha, 16) for sha in (base, head)):
        return None
    try:
        output = subprocess.check_output(
            ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}{separator}{head}", "--"],
            cwd=root,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        # Missing history must retain container coverage.
        return None
    return output.decode("utf-8", errors="surrogateescape").split("\0")[:-1]


def select_architectures(
    event_name: str,
    event: dict,
    *,
    extended: bool = False,
    release_image: bool = False,
    root: Path = Path("."),
) -> list[str]:
    if release_image:
        if event_name != "push" or not event.get("ref", "").startswith("refs/tags/rpi-v"):
            raise ValueError("Only a Pi release can use the separate image acceptance job.")
        return []
    if event_name == "workflow_dispatch":
        return EXTENDED.copy() if extended else STANDARD.copy()
    if event_name == "pull_request":
        destination = event["pull_request"]["base"]["ref"]
    elif event_name == "push" and event.get("ref", "").startswith("refs/heads/"):
        destination = event["ref"].removeprefix("refs/heads/")
    else:
        raise ValueError("Unsupported CI event.")
    if destination == "main":
        return STANDARD.copy()
    if destination == "rpi":
        return ["arm64"]
    if destination != "dev":
        raise ValueError("CI requires a dev, main, or rpi destination.")
    paths = changed_paths(event_name, event, root)
    if paths is None:
        print("Changed files are unavailable. Retain ARM64 acceptance.")
        return ["arm64"]
    if any(fnmatch.fnmatchcase(path, pattern) for path in paths for pattern in BUILD_PATHS):
        return ["arm64"]
    return []


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    architectures = select_architectures(
        os.environ["GITHUB_EVENT_NAME"],
        event,
        extended=os.environ.get("CI_EXTENDED_ARCHITECTURES") == "true",
        release_image=os.environ.get("CI_RELEASE_IMAGE") == "true",
    )
    value = json.dumps(architectures, separators=(",", ":"))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"architectures={value}\n")
    print(f"Container architectures: {value}")


if __name__ == "__main__":
    main()
