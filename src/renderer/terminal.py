"""Claude Code-style inline terminal renderer with an optional Rich backend."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, TextIO

from renderer.adapters import HarnessAdapter
from renderer.core import render_stream
from renderer.events import (
    ApprovalRequested,
    ModelFinished,
    ModelStarted,
    Notice,
    QuestionRequested,
    ReasoningDelta,
    RenderEvent,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolCallDelta,
    ToolFinished,
    ToolProgress,
    ToolStarted,
)

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.spinner import Spinner
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised with a blocked import subprocess
    Console = Group = Live = Markdown = Spinner = Text = None  # type: ignore[assignment]
    RICH_AVAILABLE = False

__all__ = [
    "RICH_AVAILABLE",
    "TerminalRenderer",
    "consume_model_stream",
    "consume_run_stream",
    "print_terminal",
    "terminal_rule",
]

_DEFAULT_CONSOLE = Console(highlight=False) if RICH_AVAILABLE else None
_OUTCOME = {
    "completed": ("✓", "green"),
    "denied": ("⊘", "yellow"),
    "failed": ("✗", "red"),
    "unknown": ("?", "magenta"),
}


def print_terminal(*values: object, style: str | None = None) -> None:
    """Print application text without making Rich a dependency."""
    message = " ".join(str(value) for value in values)
    if _DEFAULT_CONSOLE is not None:
        _DEFAULT_CONSOLE.print(Text(message, style=style))
    else:
        print(message)


def terminal_rule(title: str) -> None:
    """Print a lightweight section divider."""
    if _DEFAULT_CONSOLE is not None:
        _DEFAULT_CONSOLE.rule(Text(title, style="bold blue"), align="left")
    else:
        print(f"\n--- {title} ---")


class TerminalRenderer:
    """Pretty inline renderer for normalized events.

    ``use_rich=None`` auto-detects Rich. Set it to ``False`` for the portable
    zero-dependency backend. ``verbose=True`` preserves full tool output and
    low-level notices while the default stays close to Claude Code and Codex.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        use_rich: bool | None = None,
        verbose: bool = False,
    ) -> None:
        enabled = RICH_AVAILABLE if use_rich is None else use_rich and RICH_AVAILABLE
        backend = _RichBackend if enabled else _PlainBackend
        self._backend = backend(stream=stream, verbose=verbose)
        self.uses_rich = enabled

    def handle(self, event: RenderEvent) -> None:
        self._backend.handle(event)

    def fail(self, error: BaseException) -> None:
        self._backend.fail(error)

    def close(self) -> None:
        self._backend.close()


class _Backend:
    def __init__(self, *, verbose: bool) -> None:
        self.verbose = verbose
        self.started_at = time.monotonic()
        self.model_calls = 0
        self.text_chunks: list[str] = []
        self.reasoning_chunks: list[str] = []
        self.writing_calls: dict[int, str] = {}  # tool calls the model is still writing
        self.active_tools: dict[str, tuple[str, float]] = {}
        self.usage: dict[str, int] = {}

    def _record_usage(self, usage: dict[str, int]) -> None:
        for name, value in usage.items():
            self.usage[name] = self.usage.get(name, 0) + value

    @staticmethod
    def _arguments(arguments: dict[str, Any]) -> str:
        return ", ".join(
            f"{name}={json.dumps(value, ensure_ascii=False, default=str)}"
            for name, value in arguments.items()
        )

    @staticmethod
    def _one_line(value: str, limit: int | None = None) -> str:
        compact = " ".join(value.split())
        if limit is not None and len(compact) > limit:
            return compact[: limit - 1] + "…"
        return compact

    def _summary(self, event: RunFinished) -> str:
        parts = [f"{time.monotonic() - self.started_at:.1f}s"]
        if self.model_calls:
            parts.append(f"{self.model_calls} model call(s)")
        if "input_tokens" in self.usage:
            parts.append(f"{self.usage['input_tokens']:,} in")
        if "output_tokens" in self.usage:
            parts.append(f"{self.usage['output_tokens']:,} out")
        if "cache_read_tokens" in self.usage:
            parts.append(f"{self.usage['cache_read_tokens']:,} cached")
        if "cache_write_tokens" in self.usage:
            parts.append(f"{self.usage['cache_write_tokens']:,} cache write")
        if event.pending_count:
            parts.append(f"{event.pending_count} approval(s) pending")
        return " · ".join(parts)


class _RichBackend(_Backend):
    def __init__(self, *, stream: TextIO | None, verbose: bool) -> None:
        super().__init__(verbose=verbose)
        self.console = (
            _DEFAULT_CONSOLE
            if stream is None
            else Console(file=stream, highlight=False, force_terminal=None)
        )
        self.live: Any | None = None

    def handle(self, event: RenderEvent) -> None:
        if isinstance(event, RunStarted):
            self._run_started(event)
        elif isinstance(event, ModelStarted):
            self._model_started(event)
        elif isinstance(event, TextDelta):
            self._text_delta(event)
        elif isinstance(event, ReasoningDelta):
            self._reasoning_delta(event)
        elif isinstance(event, ToolCallDelta):
            self._tool_call_delta(event)
        elif isinstance(event, ModelFinished):
            self._model_finished(event)
        elif isinstance(event, ToolStarted):
            self._tool_started(event)
        elif isinstance(event, ToolProgress):
            self._tool_progress(event)
        elif isinstance(event, ToolFinished):
            self._tool_finished(event)
        elif isinstance(event, ApprovalRequested):
            self._approval(event)
        elif isinstance(event, QuestionRequested):
            self._question(event)
        elif isinstance(event, Notice):
            self._notice(event)
        elif isinstance(event, RunFinished):
            self._run_finished(event)

    def fail(self, error: BaseException) -> None:
        self.close()
        self._line("✗", f"{type(error).__name__}: {error}", "bold red")

    def close(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None

    def _run_started(self, event: RunStarted) -> None:
        self.console.print()
        self.console.print(Text(event.title, style="bold blue"))
        if event.prompt:
            prompt = Text()
            prompt.append("❯ ", style="bold blue")
            prompt.append(event.prompt)
            self.console.print(prompt)
        self.console.print()

    def _model_started(self, event: ModelStarted) -> None:
        self.close()
        self.text_chunks.clear()
        self.reasoning_chunks.clear()
        self.writing_calls.clear()
        self.model_calls += 1
        detail = f"Model call {self.model_calls}"
        if event.model:
            detail += f" · {event.model}"
        if self.verbose and event.message_count is not None:
            detail += f" · {event.message_count} messages"
        if self.verbose and event.tool_count is not None:
            detail += f" · {event.tool_count} tools"
        self._line("·", detail, "dim")
        self._start_live(Spinner("dots", f"{event.label}…", style="cyan"))

    def _text_delta(self, event: TextDelta) -> None:
        self.text_chunks.append(event.text)
        live_answer = Group(
            Spinner("dots", "Responding…", style="cyan"),
            Text("Assistant", style="bold green"),
            Markdown("".join(self.text_chunks)),
        )
        if self.live is None:
            self._start_live(live_answer)
        else:
            self.live.update(live_answer, refresh=True)

    def _reasoning_delta(self, event: ReasoningDelta) -> None:
        # Show the tail of the reasoning so a long think is visibly moving.
        self.reasoning_chunks.append(event.text)
        tail = self._one_line("".join(self.reasoning_chunks))[-160:]
        self._start_live(
            Group(Spinner("dots", "Thinking…", style="cyan"), Text(tail, style="dim"))
        )

    def _tool_call_delta(self, event: ToolCallDelta) -> None:
        # The first delta of a call names it. Later ones only carry argument text.
        if event.name:
            self.writing_calls[event.index] = event.name
        names = ", ".join(self.writing_calls.values()) or "a tool call"
        self._start_live(Spinner("dots", f"Writing {names}…", style="cyan"))

    def _model_finished(self, event: ModelFinished) -> None:
        self.close()
        self._record_usage(event.usage)
        if event.reasoning:
            limit = None if self.verbose else 360
            reasoning = self._one_line(event.reasoning, limit)
            self._line("◇", f"Reasoning: {reasoning}", "dim")
        if event.text:
            self.console.print(Text("Assistant", style="bold green"))
            self.console.print(Markdown(event.text))
            self.console.print()
        if event.requested_tools:
            names = ", ".join(event.requested_tools)
            self._line("↳", f"Requested {names}", "dim cyan")
        if self.verbose:
            details = [f"stop={event.stop_reason or 'unknown'}"]
            details.extend(f"{key}={value:,}" for key, value in event.usage.items())
            self._line("·", " · ".join(details), "dim")

    def _tool_started(self, event: ToolStarted) -> None:
        self.close()
        self.active_tools[event.call_id] = (event.name, time.monotonic())
        args = self._arguments(event.arguments)
        self._line("●", f"{event.name}({args})", "bold magenta")
        self._update_tools()

    def _tool_progress(self, event: ToolProgress) -> None:
        suffix = f" {event.progress:.0%}" if event.progress is not None else ""
        self._line("├", f"{event.message}{suffix}", "dim magenta")
        self._update_tools()

    def _tool_finished(self, event: ToolFinished) -> None:
        self.close()
        _, started = self.active_tools.pop(
            event.call_id, (event.name, time.monotonic())
        )
        symbol, style = _OUTCOME.get(event.status, ("·", "white"))
        elapsed = time.monotonic() - started
        self._line(
            "└", f"{symbol} {event.name} {event.status} in {elapsed:.1f}s", style
        )
        output = self._one_line(event.output, None if self.verbose else 360)
        if output:
            self._line(" ", output, "dim" if event.status == "completed" else style)
        if self.active_tools:
            self._update_tools()

    def _approval(self, event: ApprovalRequested) -> None:
        self.close()
        if event.call_id not in self.active_tools:
            args = self._arguments(event.arguments)
            self._line("●", f"{event.name}({args})", "bold magenta")
        self.active_tools.pop(event.call_id, None)
        reason = f" · {event.reason}" if event.reason else ""
        self._line("└", f"⏸ {event.name} needs approval{reason}", "bold yellow")

    def _question(self, event: QuestionRequested) -> None:
        choices = f" [{', '.join(event.choices)}]" if event.choices else ""
        self._line("?", f"{event.question}{choices}", "bold yellow")

    def _notice(self, event: Notice) -> None:
        if event.level == "debug" and not self.verbose:
            return
        symbol, style = {
            "debug": ("·", "dim"),
            "info": ("›", "cyan"),
            "warning": ("!", "yellow"),
            "error": ("✗", "red"),
        }[event.level]
        self._line(symbol, event.message, style)

    def _run_finished(self, event: RunFinished) -> None:
        self.close()
        symbol, label, style = {
            "completed": ("✓", "Done", "bold green"),
            "waiting_for_approval": ("⏸", "Waiting for approval", "bold yellow"),
            "waiting_for_input": ("?", "Waiting for input", "bold yellow"),
            "budget_exhausted": ("✗", "Model-call budget exhausted", "bold red"),
            "failed": ("✗", "Failed", "bold red"),
        }.get(event.status, ("·", event.status, "bold"))
        self._line(symbol, f"{label} · {self._summary(event)}", style)

    def _update_tools(self) -> None:
        names = ", ".join(name for name, _ in self.active_tools.values())
        self._start_live(Spinner("bouncingBar", f"Running {names}…", style="magenta"))

    def _start_live(self, renderable: Any) -> None:
        self.close()
        self.live = Live(
            renderable,
            console=self.console,
            refresh_per_second=16,
            transient=True,
        )
        self.live.start()

    def _line(self, symbol: str, message: str, style: str) -> None:
        line = Text()
        line.append(f"{symbol} ", style=style)
        line.append(message, style=style)
        self.console.print(line)


class _PlainBackend(_Backend):
    def __init__(self, *, stream: TextIO | None, verbose: bool) -> None:
        super().__init__(verbose=verbose)
        self.stream = stream or sys.stdout
        self.streaming = False

    def _write(self, value: str, *, end: str = "\n") -> None:
        self.stream.write(value + end)
        self.stream.flush()

    def handle(self, event: RenderEvent) -> None:
        if isinstance(event, RunStarted):
            self._write(f"\n{event.title}")
            if event.prompt:
                self._write(f"❯ {event.prompt}")
            self._write("")
        elif isinstance(event, ModelStarted):
            self.text_chunks.clear()
            self.streaming = False
            self.model_calls += 1
            self._write(f"· Model call {self.model_calls}")
            self._write(f"… {event.label}")
        elif isinstance(event, TextDelta):
            if not self.streaming:
                self._write("Assistant")
                self.streaming = True
            self.text_chunks.append(event.text)
            self._write(event.text, end="")
        elif isinstance(event, ReasoningDelta):
            return  # The plain view shows reasoning once, when the model finishes.
        elif isinstance(event, ToolCallDelta):
            if event.name:
                self._write(f"… writing {event.name}")
        elif isinstance(event, ModelFinished):
            self._model_finished(event)
        elif isinstance(event, ToolStarted):
            self.active_tools[event.call_id] = (event.name, time.monotonic())
            self._write(f"● {event.name}({self._arguments(event.arguments)})")
        elif isinstance(event, ToolProgress):
            suffix = f" {event.progress:.0%}" if event.progress is not None else ""
            self._write(f"├ {event.message}{suffix}")
        elif isinstance(event, ToolFinished):
            self._tool_finished(event)
        elif isinstance(event, ApprovalRequested):
            if event.call_id not in self.active_tools:
                self._write(f"● {event.name}({self._arguments(event.arguments)})")
            self.active_tools.pop(event.call_id, None)
            reason = f" · {event.reason}" if event.reason else ""
            self._write(f"└ ⏸ {event.name} needs approval{reason}")
        elif isinstance(event, QuestionRequested):
            choices = f" [{', '.join(event.choices)}]" if event.choices else ""
            self._write(f"? {event.question}{choices}")
        elif isinstance(event, Notice):
            if event.level != "debug" or self.verbose:
                symbol = "✗" if event.level == "error" else "›"
                self._write(f"{symbol} {event.message}")
        elif isinstance(event, RunFinished):
            labels = {
                "completed": "✓ Done",
                "waiting_for_approval": "⏸ Waiting for approval",
                "waiting_for_input": "? Waiting for input",
                "budget_exhausted": "✗ Model-call budget exhausted",
                "failed": "✗ Failed",
            }
            label = labels.get(event.status, event.status)
            self._write(f"{label} · {self._summary(event)}")

    def fail(self, error: BaseException) -> None:
        self._write(f"✗ {type(error).__name__}: {error}")

    def close(self) -> None:
        return

    def _model_finished(self, event: ModelFinished) -> None:
        self._record_usage(event.usage)
        if event.replace_answer and event.text:
            self._write(f'\nRevised answer\n{event.text}\n')
        elif self.streaming:
            self._write("\n")
        elif event.text:
            self._write(f"Assistant\n{event.text}\n")
        if event.reasoning:
            self._write(f"◇ Reasoning: {self._one_line(event.reasoning, 360)}")
        if event.requested_tools:
            self._write("↳ Requested " + ", ".join(event.requested_tools))

    def _tool_finished(self, event: ToolFinished) -> None:
        _, started = self.active_tools.pop(
            event.call_id, (event.name, time.monotonic())
        )
        symbol, _ = _OUTCOME.get(event.status, ("·", ""))
        elapsed = time.monotonic() - started
        self._write(f"└ {symbol} {event.name} {event.status} in {elapsed:.1f}s")
        output = self._one_line(event.output, None if self.verbose else 360)
        if output:
            self._write(f"    {output}")


async def consume_run_stream(
    source: AsyncIterator[Any],
    *,
    title: str | None = None,
    prompt: str | None = None,
    renderer: TerminalRenderer | None = None,
    on_event: Callable[[Any], None] | None = None,
) -> Any:
    """Backward-compatible convenience wrapper for this repository's harness."""
    return await render_stream(
        source,
        adapter=HarnessAdapter(),
        renderer=renderer,
        title=title or "Agent",
        prompt=prompt,
        on_raw_event=on_event,
    )


async def consume_model_stream(
    source: AsyncIterator[Any],
    *,
    request: Any,
    title: str | None = None,
    prompt: str | None = None,
    renderer: TerminalRenderer | None = None,
) -> Any:
    """Render the harness's lower-level model stream."""
    import harness

    started = False

    def adapt(event: Any):
        nonlocal started
        output: list[RenderEvent] = []
        if not started:
            output.append(
                ModelStarted(
                    message_count=len(request.messages),
                    tool_count=len(request.tools),
                )
            )
            started = True
        if isinstance(event, harness.TextDelta):
            output.append(TextDelta(event.text))
        elif isinstance(event, harness.ReasoningDelta):
            output.append(ReasoningDelta(event.text))
        elif isinstance(event, harness.ToolCallDelta):
            output.append(ToolCallDelta(event.index, event.text, event.name))
        elif isinstance(event, harness.GenerationComplete):
            message = event.message
            output.extend(
                [
                    ModelFinished(
                        text=message.text,
                        reasoning=message.reasoning,
                        stop_reason=message.stop_reason,
                        usage=message.usage,
                        requested_tools=tuple(c.name for c in message.tool_calls),
                    ),
                    RunFinished("completed", message),
                ]
            )
        return output

    return await render_stream(
        source,
        adapter=adapt,
        renderer=renderer,
        title=title or "Model",
        prompt=prompt,
    )
