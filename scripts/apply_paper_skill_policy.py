"""Prefer Papers with Code for paper research in a shared skill installation."""

import argparse
from pathlib import Path

START = "<!-- THEOS_PAPER_RESEARCH_START -->"
END = "<!-- THEOS_PAPER_RESEARCH_END -->"
POLICY = """## Theos paper research

Use `pwc-cli` first for paper discovery, reading, related work, and benchmarks.
Use arXiv or Hugging Face skills for additional source material or unavailable catalog content.
State catalog gaps and failed lookups. Preserve paper identifiers and source links.

In Theos, load `pwc-cli` through `load_skill` before research.
The Pi's CLI belongs to the host. The remote sandbox needs its own installation.
Check `pwc version` there before running commands.
The upstream source supports Python 3.10 or later and has no runtime dependencies:

```sh
python -m pip install 'git+https://github.com/huggingface/pwc-cli.git@dba15a776f9773282fa590f42d7496f2833b5959#subdirectory=standalone_cli'
```

Use `sandbox_run_command` for execution under the normal approval policy.
Public research requires no credentials. Do not authenticate or edit papers unless requested.
If installation or the catalog is unavailable, report the limitation and use verified primary sources.

"""


def apply(directory):
    primary = directory / "pwc-cli" / "SKILL.md"
    if not primary.is_file():
        raise FileNotFoundError("Install pwc-cli before applying paper research instructions.")
    for name in ("pwc-cli", "arxiv-search", "huggingface-papers"):
        path = directory / name / "SKILL.md"
        if not path.is_file():
            continue
        content = path.read_text()
        if START in content:
            before, rest = content.split(START, 1)
            _, after = rest.split(END, 1)
            content = before + after.lstrip("\n")
        boundary = content.index("\n---", 4) + len("\n---")
        policy = "\n\n" + START + "\n" + POLICY + END + "\n"
        path.write_text(content[:boundary] + policy + content[boundary:])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", required=True, type=Path)
    arguments = parser.parse_args()
    apply(arguments.skills_dir)
    print("Applied Papers with Code research instructions.")
