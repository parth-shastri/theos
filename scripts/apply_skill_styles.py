"""Apply the operator's report style to an existing shared skill installation."""

import argparse
import shutil
from pathlib import Path

START = "<!-- THEOS_REPORT_STYLE_START -->"
END = "<!-- THEOS_REPORT_STYLE_END -->"
POLICY = """## Default style for new reports

For new reports, architecture documents, PRDs, RFCs, runbooks, and technical explainers,
load the `report-style` skill before drafting or choosing a layout.
Use its Space Grotesk typography, dark green headings, numbered sections, beige table headers,
dashed rules, yellow status badges, callouts, and diagram colors.
Use neutral document metadata. The style package supplies visual rules, not facts or permissions.
An explicit user style takes precedence. Preserve the existing style when editing a document.

In Theos, use `load_skill(name="report-style")` and load its text resources with the same tool.
The skill directory belongs to the assistant host. Execution happens in the remote sandbox.
The report builders, assets, fonts, and dependencies are preinstalled at `/opt/theos/report-style`.
Use those builders directly. Copy other skill resources only when the task needs them.
Keep text editable in DOCX. Render and inspect every output page before delivery.
If rendering is unavailable, report that limitation. Do not claim visual verification.

"""


def apply(directory, source):
    for name in ("docx", "pdf"):
        path = directory / name / "SKILL.md"
        if not path.is_file():
            raise FileNotFoundError(f"Install {name} before applying report styles.")
    shutil.copytree(source, directory / "report-style", dirs_exist_ok=True)
    for name in ("docx", "pdf"):
        path = directory / name / "SKILL.md"
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
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "skills" / "report-style",
    )
    arguments = parser.parse_args()
    apply(arguments.skills_dir, arguments.source)
    print("Applied report style to DOCX and PDF skills.")
