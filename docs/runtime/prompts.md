# Prompt templates

Theos and the harness store prompts as ordinary `.md` files with Jinja syntax.
Open these files in a Markdown preview to read their text.
Jinja renders conditionals and includes when the application builds a model request.
Markdown previews show the template source rather than the rendered branches.

## Ownership

| Directory | Contents |
| --- | --- |
| `src/harness/prompts/compaction/` | Production summary, update, split-turn, shortening, and checkpoint prompts |
| `src/harness/prompts/execution/` | Generic tool execution guidance |
| `src/theos/prompts/chat/` | Assistant identity, user context, and capability composition |
| `src/theos/prompts/shared/` | Personality and writing rules |
| `src/theos/prompts/capabilities/` | Research, workspace, and skill policies |
| `src/theos/prompts/delegates/` | Application research delegate instructions |
| `src/theos/prompts/recovery/` | Remote review and final response instructions |
| `src/theos/prompts/titles/`, `speech/`, `memory/`, `channels/` | Task and transport prompts |
| `src/theos/prompts/compaction/` | Optional Theos overrides of harness production prompts |

The harness owns the compaction algorithm and its production defaults.
Theos uses those defaults unless its release includes explicit override files.
Tool schemas, permission checks, retrieval, and message roles remain in Python.

## Prompt structure

Main prompts separate their purpose and rules with Markdown headings:

```markdown
# Role and Identity

# Personality and Voice

# Instructions

# Response Format

# Examples

# Runtime Context
```

Use only the sections a task needs. A reusable fragment does not need a separate identity.
Keep operational rules separate from response style and runtime data.
Place dynamic preferences and retrieved memory in labeled blocks after the stable chat instructions.
Examples illustrate behavior. Their details are not evidence for the current task.

Theos chat and speech preparation include `shared/personality.md`.
Speech source preservation takes precedence over style. Delegates and harness summaries use factual language.
Compaction prompts distinguish role, task, preservation rules, and the requested summary format.
Shortening calls still request prose without summary headings.

This structure follows [OpenAI's prompt guidance](https://developers.openai.com/api/docs/guides/prompt-engineering)
and [Anthropic's guidance](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices).
The exact sections depend on the task. They are not a required schema for every fragment.

## Render a prompt

`src/harness/prompting.py` provides a package-aware Jinja environment.
Theos calls it through `src/theos/prompts/__init__.py`.

```python
from theos.prompts import render

instructions = render(
    "delegates/system.md",
    delegate_name="Source reader",
    research_enabled=True,
    allow_delegation=False,
)
```

Templates receive plain values. Python resolves enabled capabilities and reads external data.
Use Jinja for text conditions and includes:

```jinja
{% if sandbox_enabled %}
{% include "capabilities/sandbox.md" %}
{% endif %}
```

Includes resolve within their owning package.
Keep user preferences, retrieved memory, and installed skill contents as template values.
Render trusted package files once. Inserted values retain literal Jinja syntax and Markdown characters.
Do not pass service clients, database handles, or secrets into template context.

Missing variables fail through `StrictUndefined`. Prompt text uses no HTML escaping.
Templates own their paragraph breaks and section boundaries. Keep includes separated so adjacent instructions cannot run together.
Runtime startup compiles templates and checks static includes.
Request values remain local to each render. The cache stores compiled templates only.

## Override compaction prompts

Add only the files that need different instructions under `src/theos/prompts/compaction/`.
The runtime passes their rendered text through `CompactionConfig` for parent, delegate, and recovery agents.

| Optional Theos file | Configuration field |
| --- | --- |
| `system.md` | `prompt` |
| `initial.md` | `initial_prompt` |
| `update.md` | `update_prompt` |
| `turn_prefix.md` | `turn_prefix_prompt` |
| `shorten.md` | `shortening_prompts` |
| `additional.md` | `additional_instructions` |

Each absent file retains the corresponding harness default.
An invalid override fails explicitly. It does not silently select a different prompt.
Theos currently ships no compaction overrides.

`shorten.md` receives `tier` and `length` for three rendered prompts:

| Tier | Length |
| --- | --- |
| 1 | `a short paragraph` |
| 2 | `three short sentences` |
| 3 | `one concise sentence` |

For example, a custom shortening template can contain:

```jinja
Shortening pass {{ tier }}: summarize the previous checkpoint in {{ length }}.
Preserve requirements, confirmed outcomes, unresolved work, and uncertainty.
```

Standalone harness callers can pass the same configuration fields directly.
The existing `prompt`, options, callbacks, ratios, and model settings remain available.
Prompt selection, split-turn coverage, context ordering, and tool execution remain harness responsibilities.

## Release and verify

Prompt edits ship with code through normal releases.
Package resources load from installed wheels without relying on the repository working directory.
Production processes cache templates. Restart with the new release to activate edits.

Run the focused checks:

```sh
uv run pytest tests/test_prompting.py tests/test_compaction.py tests/app/test_prompt_overrides.py
uv build --wheel
```

The initial extraction preserved existing text and message order.
The structured revision changes wording and placement while retaining capability gates, operation selection, and context ordering.
Review the assembled prompt and representative outputs when changing these instructions.
