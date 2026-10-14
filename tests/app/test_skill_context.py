"""Purpose-based skill catalog and automatic report instructions before generation."""

from contextlib import asynccontextmanager

from harness import AssistantMessage
from harness.testing import FakeModel
from theos.services.skills.context import skill_context, skill_description

from .conftest import collect


def install(settings, tmp_path):
    settings.skills_dir = tmp_path / "skills"
    for name, description in [
        ("report-style", "House report layout"),
        ("pdf", "Create and inspect PDF files"),
        ("xlsx", "Create spreadsheets"),
        ("pwc-cli", "Find research papers"),
    ]:
        path = settings.skills_dir / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\nInstruction body for {name}."
        )


def test_catalog_describes_skills_without_loading_unrelated_workflows(settings, tmp_path):
    install(settings, tmp_path)
    content, loaded = skill_context(settings, "Research carbon capture papers")
    assert "Find research papers" in content and "Create spreadsheets" in content
    assert "match the user's intent to skill descriptions" in content
    assert "Do not load every skill" in content and not loaded
    assert "Instruction body for xlsx" not in content


async def test_report_style_is_present_before_first_model_call_without_explicit_skill_request(
    runtime, tmp_path
):
    install(runtime.settings, tmp_path)
    model = FakeModel([AssistantMessage("Prepared report.")])

    @asynccontextmanager
    async def models(*args):
        yield model

    runtime.models = models
    row = runtime.db.create_session("alice", "test", "none")
    turn = runtime.start("alice", row["id"], "Generate a report about my receipts")
    events = await collect(turn)
    assert events[-1]["stats"]["skills"] == ["pdf", "report-style"]
    content = str(model.requests[0])
    assert "Instruction body for report-style" in content and "Instruction body for pdf" in content
    assert "styled PDF by default" in content and "Explicit user formats" in content


def test_multiline_skill_descriptions_preserve_task_selection_guidance():
    content = "---\nname: analysis\ndescription: >-\n  Compare evidence from multiple sources.\n  Use when assessing conflicting research.\nother: value\n---\nBody"
    assert skill_description(content) == (
        "Compare evidence from multiple sources. Use when assessing conflicting research."
    )
