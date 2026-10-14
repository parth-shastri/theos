"""Expose installed skills and supply report instructions before drafting."""

import re

from .tools import read_skill


def skill_description(content):
    """Read plain, quoted, and multiline descriptions from skill frontmatter."""
    front = re.match(r"\A---\s*\n(.*?)\n---(?:\n|$)", content, re.DOTALL)
    if not front:
        return "Read this skill to inspect its workflow."
    description = re.search(r"^description:[ \t]*(.*)((?:\n[ \t]+[^\n]*)*)", front[1], re.MULTILINE)
    if not description:
        return "Read this skill to inspect its workflow."
    first, continuation = description.groups()
    if first.strip() in {">", "|", ">-", "|-", ">+", "|+"}:
        first = ""
    return " ".join((first + continuation).strip().strip("\"'").split())[:1000]


def skill_context(settings, task):
    """Load actual instructions. Explicit formats and existing styles retain precedence."""
    root = settings.skills_dir
    if not root:
        return "", []
    names = sorted(p.parent.name for p in root.glob("*/SKILL.md"))[:64]
    catalog = []
    for name in names:
        try:
            value = read_skill(settings, name)
        except (LookupError, ValueError, OSError):
            continue
        catalog.append(f"- {name}: {skill_description(value['content'])}")
    instructions = (
        "Before doing a task, inspect the skill catalog below and match the user's intent to skill descriptions. "
        "Load applicable skill instructions with load_skill before doing their work, even when the user did not name a skill. "
        "Choose relevant skills intelligently. Do not load every skill, rely only on a name match, or run irrelevant workflows. "
        "Use complementary skills together when their workflows require it. Skills can guide research, code review, "
        "spreadsheets, document reading, and document creation. Follow each loaded workflow and its required resources. "
        "For a new report, use report-style before drafting and pdf or docx for the selected format. "
        "A request to generate a report means deliver a styled PDF by default. "
        "Explicit user formats and styles take precedence. Summarizing an existing report does not require a new file. "
        "Keep Markdown as a source when useful. Load scripts and assets through load_skill's resource argument, "
        "copy them into the sandbox, build with the skill's workflow, and inspect every output page before delivery. "
        "Host skill paths are not sandbox paths. Do not substitute a generic PDF renderer for the installed report workflow. "
        "If required skills or dependencies are unavailable, explain the limitation before using a fallback."
    )
    instructions += (
        "\n<installed_skill_catalog>\n" + "\n".join(catalog) + "\n</installed_skill_catalog>"
    )
    requested = []
    if re.search(r"\b(report|pdf|docx|document|word)\b", task, re.IGNORECASE):
        requested = [
            "report-style",
            "docx" if re.search(r"\b(docx|word)\b", task, re.IGNORECASE) else "pdf",
        ]
    loaded = []
    for name in requested:
        try:
            value = read_skill(settings, name)
        except (LookupError, ValueError, OSError):
            instructions += (
                f"\nRequired skill unavailable: {name}. Report this limitation accurately."
            )
            continue
        instructions += f"\n<operator_skill name='{name}'>\n{value['content']}\n</operator_skill>"
        loaded.append(name)
    return instructions, loaded
