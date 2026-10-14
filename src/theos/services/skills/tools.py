"""Skills tools with bounded responses."""

from harness import tool
from theos.services.errors import ServiceError


def read_skill(settings, name, resource="SKILL.md"):
    """Read an operator skill through the same boundary used by automatic context."""
    if not settings.skills_dir:
        raise ServiceError("Set AGENT_SKILLS_DIR to enable local skills.")
    root = settings.skills_dir.resolve()
    directory = (root / name).resolve()
    path = (directory / resource).resolve()
    if directory.parent != root or not path.is_relative_to(directory) or not path.is_file():
        raise LookupError("Skill resource not found.")
    if path.stat().st_size > 64000:
        raise ValueError("The skill resource exceeds 64 KB.")
    return {"name": name, "resource": resource, "content": path.read_text()}


def skills_tools(settings, http):
    """Build read-only tools for operator-installed skill resources."""

    @tool
    async def list_skills():
        """List the skill instructions installed by the operator."""
        root = settings.skills_dir
        return sorted(p.parent.name for p in root.glob("*/SKILL.md")) if root else []

    @tool
    async def load_skill(name: str, resource: str = "SKILL.md"):
        """Read a skill or a resource inside its directory."""
        return read_skill(settings, name, resource)

    return [list_skills, load_skill]
