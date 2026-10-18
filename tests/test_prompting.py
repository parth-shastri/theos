"""Packaged prompt rendering preserves data boundaries and explicit failures."""

from importlib.resources import files

import pytest
from jinja2 import TemplateNotFound, UndefinedError

from harness.prompting import prompt_names, render_prompt, validate_prompts
from theos.prompts import render


@pytest.mark.parametrize("package", ["harness", "theos"])
def test_prompt_resources_compile_and_load_without_the_repository_cwd(
    package, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    validate_prompts(package)
    assert prompt_names(package)
    for name in prompt_names(package):
        assert name.endswith(".md")
        assert (files(package) / "prompts" / name).is_file()


def test_missing_template_or_required_context_fails_explicitly():
    with pytest.raises(TemplateNotFound):
        render_prompt("harness", "compaction/absent.md")
    with pytest.raises(UndefinedError, match="length"):
        render_prompt("harness", "compaction/shorten.md", tier=1)


def chat_context(**changes):
    return (
        dict(
            agent_name="Theos",
            current_utc="2026-10-18T12:00:00+00:00",
            preferences_json="{}",
            recovery_review=False,
            sandbox_enabled=False,
            skill_instructions="",
            research_enabled=False,
            allow_delegation=True,
            retrieved_memory="",
            telegram=False,
        )
        | changes
    )


@pytest.mark.parametrize(
    "sandbox,review,research,telegram",
    [
        (False, False, False, False),
        (True, False, False, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, True),
        (True, True, True, True),
    ],
)
def test_chat_capability_branches(sandbox, review, research, telegram):
    text = render(
        "chat/system.md",
        **chat_context(
            sandbox_enabled=sandbox,
            recovery_review=review,
            research_enabled=research,
            telegram=telegram,
        ),
    )
    assert ("Keep task files under /workspace" in text) == sandbox
    assert ("restored from a remote checkpoint" in text) == review
    assert ("user explicitly enabled deep research" in text) == research
    assert ("This is a normal turn" in text) != research
    assert ("Your reply will appear in Telegram" in text) == telegram


def test_request_values_remain_literal_and_do_not_leak_between_renders():
    literal = "{{ secret }} {% include 'missing.md' %} <personal> & data"
    alice = render("chat/system.md", **chat_context(agent_name="Alice", retrieved_memory=literal))
    bob = render("chat/system.md", **chat_context(agent_name="Bob"))
    assert literal in alice
    assert literal not in bob
    assert "Alice" not in bob
    assert "You are Bob" in bob
    sections = [
        "# Role and Identity",
        "# Personality and Voice",
        "# Instructions",
        "# Response Format",
        "# Examples",
        "# Runtime Context",
    ]
    positions = [bob.index(section) for section in sections]
    assert positions == sorted(positions)
    assert "<user_preferences>\n{}\n</user_preferences>" in bob
    checkpoint = render_prompt(
        "harness", "compaction/checkpoint.md", label="Checkpoint", summary=literal
    )
    assert literal in checkpoint


def test_delegate_research_policy_has_an_explicit_delegation_condition():
    parent = render("capabilities/research.md", allow_delegation=True)
    child = render(
        "delegates/system.md",
        delegate_name="Source reader",
        research_enabled=True,
        allow_delegation=False,
    )
    assert "Use deep_research for independent assignments" in parent
    assert "Use deep_research for independent assignments" not in child
    assert "Read important original sources with read_source" in child
    assert "# Personality and Voice" not in child


def test_operator_skill_contents_are_not_rendered_as_templates():
    literal = "{{ unknown }} {% if broken %} <operator data>"
    text = render(
        "capabilities/skills.md",
        catalog=["- pdf: Documents"],
        selected_skills=[{"name": "pdf", "content": literal}],
    )
    assert literal in text
