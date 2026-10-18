"""Theos-owned prompts and optional overrides of harness production defaults."""

from harness.prompting import prompt_names, render_prompt


def render(name: str, **context) -> str:
    return render_prompt("theos", name, **context)


def compaction_overrides() -> dict:
    """Load only explicit release-owned overrides. Missing files use harness defaults.

    Theos override present -> CompactionConfig field
    Theos override absent  -> harness production default
    """
    names = prompt_names("theos")
    overrides = {}
    for field, filename in (
        ("prompt", "system.md"),
        ("initial_prompt", "initial.md"),
        ("update_prompt", "update.md"),
        ("turn_prefix_prompt", "turn_prefix.md"),
        ("additional_instructions", "additional.md"),
    ):
        name = f"compaction/{filename}"
        if name in names:
            overrides[field] = render(name)
    if "compaction/shorten.md" in names:
        overrides["shortening_prompts"] = tuple(
            render("compaction/shorten.md", tier=tier, length=length)
            for tier, length in enumerate(
                ("a short paragraph", "three short sentences", "one concise sentence"), 1
            )
        )
    return overrides
