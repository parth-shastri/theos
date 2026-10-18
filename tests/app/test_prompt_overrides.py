"""Theos overrides are release-owned and fall back independently to the harness."""

import pytest
from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    PackageLoader,
    StrictUndefined,
    UndefinedError,
)

from harness import CompactionConfig, prompting
from harness.compaction import DEFAULT_SHORTENING_PROMPTS, INITIAL_SUMMARY_PROMPT
from theos.prompts import compaction_overrides
from theos.runtime import context


@pytest.fixture
def override_templates(monkeypatch):
    def install(templates):
        environment = Environment(
            loader=ChoiceLoader([DictLoader(templates), PackageLoader("theos", "prompts")]),
            undefined=StrictUndefined,
            autoescape=False,
        )
        monkeypatch.setattr(prompting, "_environment", lambda package: environment)
        prompting.prompt_names.cache_clear()

    yield install
    prompting.prompt_names.cache_clear()


def test_partial_override_reaches_runtime_config_without_replacing_other_defaults(
    runtime, override_templates
):
    override_templates({"compaction/update.md": "Theos update instructions."})
    session = runtime.db.create_session("alice", "test", "none")
    config = context.compaction(runtime, session, context.ModelCapacity(100_000, 8192, "test"))
    assert config.update_prompt == "Theos update instructions."
    assert config.initial_prompt == INITIAL_SUMMARY_PROMPT
    assert config.shortening_prompts == DEFAULT_SHORTENING_PROMPTS
    assert config.on_commit and config.on_summary


def test_all_compaction_overrides_and_shortening_context_are_supported(override_templates):
    override_templates(
        {
            "compaction/system.md": "Theos shared instructions.",
            "compaction/initial.md": "Theos initial instructions.",
            "compaction/update.md": "Theos update instructions.",
            "compaction/turn_prefix.md": "Theos split-turn instructions.",
            "compaction/shorten.md": "Tier {{ tier }}: {{ length }}.",
            "compaction/additional.md": "Preserve pending approvals.",
        }
    )
    config = CompactionConfig(**compaction_overrides())
    assert config.prompt == "Theos shared instructions."
    assert config.initial_prompt == "Theos initial instructions."
    assert config.update_prompt == "Theos update instructions."
    assert config.turn_prefix_prompt == "Theos split-turn instructions."
    assert config.additional_instructions == "Preserve pending approvals."
    assert config.shortening_prompts == (
        "Tier 1: a short paragraph.",
        "Tier 2: three short sentences.",
        "Tier 3: one concise sentence.",
    )


def test_invalid_override_does_not_silently_use_a_default(override_templates):
    override_templates({"compaction/update.md": "{{ missing_context }}"})
    with pytest.raises(UndefinedError):
        compaction_overrides()
