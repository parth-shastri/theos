#!/usr/bin/env python3
"""Build a report from Markdown with the preinstalled report style."""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--format", choices=("pdf", "docx"), default="pdf")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    source = args.markdown
    if not source.is_file():
        parser.error(f"Markdown source does not exist: {source}")

    output = args.out or source.with_suffix("." + args.format)
    output.parent.mkdir(parents=True, exist_ok=True)
    builder = Path(__file__).with_name("build_doc.py" if args.format == "pdf" else "build_docx.py")
    result = subprocess.run(
        [sys.executable, str(builder), str(source), "--out", str(output)],
        check=False,
    )
    if result.returncode:
        return result.returncode
    if not output.is_file() or output.stat().st_size == 0:
        print(f"Report builder did not create {output}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
