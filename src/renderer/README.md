# Composable agent renderer

The renderer consumes a small event vocabulary rather than framework-specific
objects. This keeps the UI independent from the agent runtime.

## One-call usage

`render_stream` accepts both `Iterable` and `AsyncIterable` sources. Its default
adapter recognizes the local harness, common LangGraph stream shapes,
smolagents streaming steps, strings, and objects with a `content` attribute.

```python
from renderer import render_stream

result = await render_stream(
    agent.run_stream(history),
    title="Support agent",
    prompt="Where is my order?",
)
```

Blocking generators, including `smolagents` streams, are advanced in a worker
thread so the terminal animation remains responsive:

```python
from renderer import SmolAgentsAdapter, render_stream

result = await render_stream(
    agent.run(task, stream=True),
    adapter=SmolAgentsAdapter(),
    prompt=task,
)
```

LangGraph message tuples and `astream_events` dictionaries can be explicit when
automatic detection is not desired:

```python
from renderer import LangGraphAdapter, render_stream

result = await render_stream(
    graph.astream(inputs, stream_mode="messages"),
    adapter=LangGraphAdapter(),
    prompt=question,
)
```

## Supporting any other framework

An adapter is one callable. It receives a raw framework event and returns one
normalized event, an iterable of events, or `None`.

```python
from renderer import RunFinished, TextDelta, ToolStarted, render_stream


def adapt(chunk):
    match chunk.kind:
        case "token":
            return TextDelta(chunk.text)
        case "tool":
            return ToolStarted(chunk.id, chunk.name, chunk.arguments)
        case "done":
            return RunFinished("completed", chunk.result)
    return None


result = await render_stream(agent.events(), adapter=adapt)
```

The public vocabulary is in `renderer.events`: `RunStarted`, `ModelStarted`,
`TextDelta`, `ModelFinished`, `ToolStarted`, `ToolProgress`, `ToolFinished`,
`ApprovalRequested`, `QuestionRequested`, `Notice`, and `RunFinished`.

Streams crossing a process boundary may emit the same protocol as dictionaries,
for example `{"type": "text_delta", "text": "hello"}` or
`{"type": "tool_started", "name": "search", "toolCallId": "1", "data":
{"arguments": {"query": "agents"}}}`. Auto-normalization accepts these JSON
shapes directly.

## Composition

Renderers only implement three synchronous methods: `handle(event)`,
`fail(error)`, and `close()`. `CompositeRenderer` fans events out to multiple
backends, while `observe` receives every normalized event for telemetry or
recording.

```python
from renderer import CompositeRenderer, TerminalRenderer, render_stream

ui = CompositeRenderer(TerminalRenderer(), jsonl_recorder)
await render_stream(stream, renderer=ui, observe=metrics.record)
```

For callback-driven runtimes, `make_event_handler` turns the same adapter into a
normal synchronous callback.

## Terminal behavior

The default terminal UI is deliberately inline, like Claude Code and Codex. It
keeps the prompt, streamed answer, tool tree, approvals, errors, timing, and
token totals in the normal terminal scrollback. Rich adds Markdown, color, and
live spinners when available; the plain backend has no third-party dependency.

## Interactive sessions

For the Theos application, install the `terminal` extra and run `theos`.
The [terminal guide](../../docs/terminal.md) covers local settings, sessions, images, steering, and approvals.

`HarnessTui` provides persistent sessions, steering, approval replies, image
attachments, and history. `AgentSession` adapts this repository's `Agent` and
`Store`; `HarnessBinding` adapts another runtime through callables.

Install the optional UI dependencies and launch any `InteractiveSession`,
`AgentSession`, or zero-argument factory:

```sh
uv run --extra terminal harness-cli your_package.cli:session --session demo
```

The `terminal` extra installs Rich and Textual. The event adapters and inline
terminal renderer remain usable without Textual.

The TUI nests subagent activity under its parent tool. Thinking, tools, and
intermediate answers use gray, regular-weight text with clickable disclosures.
The final answer stays expanded and shows token usage once. Timestamps use
local time, for example `29th September 26, 10:40`.

Use `/new` to clear the transcript and create a new session. Use `/resume` to
search saved sessions, filter by directory or archive status, and change the
sort order. Enter resumes the selection. Tab selects a filter and arrow keys
change it. Ctrl+A archives or restores the selected session. `/sessions` is
removed. `/rename <title>` assigns a name that automatic titles do not replace.

`AgentSession` derives titles from the first substantive request. `MemoryStore`
and `JsonlStore` also save timestamps, directory, archive status, and compaction
memory. JSONL stores keep this state in separate `.state.json` files. Existing
JSONL transcripts remain readable. Custom stores can implement `load_state(key)`
and `save_state(key, state)` for the same persistence. Without those methods,
session metadata and context memory remain in the `AgentSession` instance.

Other runtimes can supply `SessionInfo` through
`HarnessBinding.list_session_details` and timestamps through `load_timestamps`.
Custom event adapters can set `parent_call_id` to place events under a tool.
Harness tools inherit this scope automatically when they forward child events
through `ctx.emit(event)`.

## Context compaction

Compaction is optional and requires a context window. Configure the summary
prompt and output budget on the agent:

```python
from harness import Agent, CompactionConfig, JsonlStore
from pathlib import Path
from renderer import AgentSession

agent = Agent(
    model,
    tools,
    context_window=32768,
    compaction=CompactionConfig(
        prompt="Summarize the task, findings, sources, and unresolved questions.",
        options={"max_tokens": 512},
    ),
)
session = AgentSession(agent, JsonlStore(Path(".sessions")))
```

The harness uses the same model to update the rolling summary without tools.
Production prompts live in `src/harness/prompts/compaction/` as Markdown Jinja templates.
`CompactionConfig` accepts `initial_prompt`, `update_prompt`, `turn_prefix_prompt`, and three `shortening_prompts`.
Omitted fields retain their production defaults. `prompt` supplies shared instructions and `additional_instructions` adds optional focus.
Split turns use separate history and turn-prefix summaries.
The combined checkpoint precedes retained messages and includes the covered original request.
New unanswered requests remain verbatim. The complete history stays unchanged.
Large messages keep their history indexes for exact retrieval.
Provider overflow retries use shorter summary tiers without rerunning completed tools.
Direct callers can pass a `ContextMemory` instance through `Agent.run` or
`Agent.run_stream` to retain summaries between turns.
