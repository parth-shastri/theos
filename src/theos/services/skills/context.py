"""Expose installed skills and supply report instructions before drafting."""

import re

from theos.prompts import render

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
    requested = []
    if re.search(r"\b(report|pdf|docx|document|word)\b", task, re.IGNORECASE):
        requested = [
            "report-style",
            "docx" if re.search(r"\b(docx|word)\b", task, re.IGNORECASE) else "pdf",
        ]
    loaded = []
    selected_skills = []
    for name in requested:
        try:
            value = read_skill(settings, name)
        except (LookupError, ValueError, OSError):
            selected_skills.append({"name": name, "content": None})
            continue
        selected_skills.append({"name": name, "content": value["content"]})
        loaded.append(name)
    return render(
        "capabilities/skills.md", catalog=catalog, selected_skills=selected_skills
    ), loaded
