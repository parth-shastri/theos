"""Purpose-based skill catalog and automatic report instructions before generation."""

from harness import AssistantMessage
from theos.services.skills.context import skill_context

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
    runtime, scripted_models, tmp_path
):
    install(runtime.settings, tmp_path)
    scripted_models.responses.append([AssistantMessage("Prepared report.")])
    row = runtime.db.create_session("alice", "test", "none")
    turn = runtime.start("alice", row["id"], "Generate a report about my receipts")
    events = await collect(turn)
    assert events[-1]["stats"]["skills"] == ["pdf", "report-style"]
    content, loaded = skill_context(runtime.settings, "Generate a report")
    assert "Instruction body for report-style" in content and "Instruction body for pdf" in content
    assert "styled PDF by default" in content and "Explicit user formats" in content
    assert loaded == ["report-style", "pdf"]
