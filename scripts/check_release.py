"""Reject Raspberry Pi release tags that do not identify the current rpi revision."""

import argparse
import re
import subprocess
import tomllib
from pathlib import Path


def check_release(tag: str, root: Path = Path(".")) -> str:
    match = re.fullmatch(r"rpi-v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag)
    if not match:
        raise ValueError("Use a release tag such as rpi-v0.1.0.")
    version = tag.removeprefix("rpi-v")
    configured = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if version != configured:
        raise ValueError(f"Tag version {version} differs from package version {configured}.")

    def revision(ref):
        return subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=root, text=True
        ).strip()

    head = revision("HEAD")
    if head != revision(f"refs/tags/{tag}") or head != revision("refs/remotes/origin/rpi"):
        raise ValueError("The release tag must point to the current origin/rpi commit.")
    return head


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    try:
        print(check_release(args.tag))
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release rejected: {error}\n")


if __name__ == "__main__":
    main()
