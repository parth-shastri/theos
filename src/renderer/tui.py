"""Inline, Codex-style terminal UI for interactive agent harnesses."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from uuid import uuid4
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from harness import ImageInput, normalize_token_usage
from harness.titles import conversation_title
from renderer.adapters import Adapter
from renderer.clipboard import ClipboardImageError, read_clipboard_image
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
from renderer.interactive import (
    AgentSession,
    InteractionReply,
    InteractionRequest,
    InteractiveSession,
    PromptInput,
    RuntimeInfo,
    SessionInfo,
    await_if_needed,
    normalize_prompt,
)

try:
    from rich.console import Group
    from rich.markdown import Markdown
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.segment import Segment
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text
    from textual import events, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
    from textual.screen import ModalScreen
    from textual.widgets import Button, Input, Label, OptionList, Static
    from textual.widgets.option_list import Option

    TEXTUAL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional UI runtime
    Group = Markdown = Padding = Panel = Segment = Style = Table = Text = None  # type: ignore[assignment]
    App = ModalScreen = object  # type: ignore[assignment,misc]
    ComposeResult = Any  # type: ignore[assignment,misc]
    Container = Horizontal = Vertical = VerticalScroll = object  # type: ignore[assignment,misc]
    Binding = Button = Input = Label = Option = OptionList = Static = object  # type: ignore[assignment,misc]
    TEXTUAL_AVAILABLE = False

__all__ = ["HarnessTui", "TEXTUAL_AVAILABLE", "TuiRenderer", "run_tui"]

_DETAIL_COLOR = "#89929d"
_DETAIL_STYLE = f"{_DETAIL_COLOR} not bold"

_COMMANDS = (
    ("/help", "Show every command"),
    ("/resume", "Resume an existing session"),
    ("/new", "Clear the screen and start a new session"),
    ("/rename", "Name the current conversation"),
    ("/permissions", "Show the permission policy"),
    ("/thinking", "Expand or collapse the latest reasoning trace"),
    ("/tools", "Expand or collapse the latest tool call"),
    ("/status", "Show session and run status"),
    ("/reload", "Reload persisted history"),
    ("/clear", "Clear the visible transcript"),
    ("/quit", "Exit the harness"),
)
_COMMANDS_WITH_ARGUMENT = {"/rename"}

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_IGNORED_ATTACHMENT_DIRS = frozenset(
    {
        ".git",
        ".next",
        ".runs",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)

_HELP_SECTIONS = (
    (
        "SESSIONS",
        (
            ("/resume", "Choose from saved sessions"),
            ("/new", "Clear the screen and start a fresh session"),
            ("/rename <name>", "Name the current conversation"),
            ("/reload", "Reload the current saved transcript"),
        ),
    ),
    (
        "INSPECT",
        (
            ("/status", "Model, provider, session, tools, and storage"),
            ("/permissions", "Active approval boundary and tool policy"),
            ("/thinking", "Toggle the latest reasoning trace"),
            ("/tools", "Toggle the latest tool call"),
        ),
    ),
    (
        "ATTACH",
        (
            ("@", "Find and attach an image file"),
            ("Ctrl+V", "Attach an image from the clipboard"),
            ("Backspace", "Remove the latest attachment when input is empty"),
        ),
    ),
    (
        "GENERAL",
        (
            ("/help", "Open this command guide"),
            ("/clear", "Clear only the visible transcript"),
            ("/quit", "Exit the harness"),
        ),
    ),
    (
        "KEYBOARD",
        (
            ("Ctrl+R", "Toggle reasoning"),
            ("Ctrl+T", "Toggle tool details"),
            ("Ctrl+L", "Clear the visible transcript"),
            ("Ctrl+C", "Exit"),
        ),
    ),
)


@dataclass(frozen=True)
class _SessionChoice:
    session_id: str
    message_count: int
    preview: str
    title: str = ''
    created_at: str | None = None
    updated_at: str | None = None
    cwd: str | None = None
    archived: bool = False


@dataclass
class _ThinkingBlock:
    index: int
    label: str
    started_at: float
    content: str = ""
    elapsed: float = 0.0
    active: bool = True
    expanded: bool = False
    timestamp: str | None = field(default_factory=lambda: datetime.now().astimezone().isoformat())


@dataclass
class _ToolBlock:
    index: int
    call_id: str
    name: str
    arguments: dict[str, Any]
    output: str = ""
    status: str = "requested"
    progress: list[str] = field(default_factory=list)
    expanded: bool = False
    has_children: bool = False
    timestamp: str | None = field(default_factory=lambda: datetime.now().astimezone().isoformat())


@dataclass
class _ResponseBlock:
    index: int
    content: str
    usage: dict[str, int] | None = None
    stop_reason: str | None = None
    collapsible: bool = False
    expanded: bool = False
    timestamp: str | None = field(default_factory=lambda: datetime.now().astimezone().isoformat())


@dataclass
class _ModelState:
    text: str = ""
    response_index: int | None = None
    thinking: _ThinkingBlock | None = None
    tool_drafts: dict[int, tuple[str, str]] = field(default_factory=dict)


_BUFFER_FRAMES = (
    "▰▱▱▱▱",
    "▱▰▱▱▱",
    "▱▱▰▱▱",
    "▱▱▱▰▱",
    "▱▱▱▱▰",
    "▱▱▱▰▱",
    "▱▱▰▱▱",
    "▱▰▱▱▱",
)


def _role(message: Any) -> str:
    name = type(message).__name__.lower()
    if name.startswith("user"):
        return "user"
    if name.startswith("assistant"):
        return "assistant"
    if name.startswith("tool"):
        return "tool"
    return "system"


def _text(message: Any) -> str:
    if hasattr(message, "content"):
        return str(message.content)
    return str(getattr(message, "text", None) or "")


def _images(message: Any) -> Sequence[ImageInput]:
    value = getattr(message, "images", ())
    return value if isinstance(value, Sequence) else ()


if TEXTUAL_AVAILABLE:

    class _MutedMarkdown(Markdown):
        """Keep expanded intermediate answers readable but visually secondary."""

        def __rich_console__(self, console, options):
            yield from Segment.apply_style(
                super().__rich_console__(console, options),
                post_style=Style(color=_DETAIL_COLOR, bold=False, dim=False, underline=False),
            )

    class _Transcript(Static):
        pass

    class InteractionScreen(ModalScreen[InteractionReply]):
        """Bottom-docked approval or question prompt, matching CLI flow."""

        CSS = """
        InteractionScreen {
            background: #00000000;
            align: center bottom;
        }
        #interaction {
            width: 100%;
            max-width: 112;
            height: auto;
            max-height: 70%;
            padding: 1 3 2 3;
            background: #0d0f12;
            border-top: solid #343a46;
        }
        #interaction-kind {
            color: #d8a657;
            text-style: bold;
        }
        #interaction-title {
            margin: 1 0;
            color: #f0f3f6;
            text-style: bold;
        }
        #interaction-detail {
            max-height: 14;
            color: #a7adb8;
            margin-bottom: 1;
        }
        #interaction-options {
            height: auto;
        }
        #interaction-options Button {
            width: 100%;
            height: 1;
            min-width: 1;
            padding: 0 1;
            margin: 0;
            border: none;
            background: #00000000;
            color: #c9d1d9;
            text-align: left;
        }
        #interaction-options Button:focus {
            background: #20252d;
            color: #f0f6fc;
            text-style: bold;
        }
        #interaction-input {
            margin-top: 1;
            height: 3;
            border: tall #343a46;
            background: #0d0f12;
        }
        """
        BINDINGS = [("escape", "cancel", "Cancel")]

        def __init__(self, request: InteractionRequest) -> None:
            super().__init__()
            self.request = request

        def compose(self) -> ComposeResult:
            with Container(id="interaction"):
                if isinstance(self.request, ApprovalRequested):
                    yield Label("Permission required", id="interaction-kind")
                    yield Label(
                        f"Allow {self.request.name} to run?",
                        id="interaction-title",
                    )
                    detail = _approval_detail(self.request)
                    if detail:
                        yield Static(detail, id="interaction-detail")
                    with Vertical(id="interaction-options"):
                        yield Button("› 1. Allow once", id="allow")
                        yield Button("  2. Deny", id="deny")
                    yield Input(
                        placeholder="Optional denial reason",
                        id="interaction-input",
                    )
                else:
                    yield Label("Input required", id="interaction-kind")
                    yield Label(self.request.question, id="interaction-title")
                    if self.request.choices:
                        with Vertical(id="interaction-options"):
                            for index, choice in enumerate(self.request.choices, start=1):
                                yield Button(
                                    f"  {index}. {choice}",
                                    id=f"choice-{index - 1}",
                                )
                    if self.request.allow_free_text:
                        yield Input(
                            placeholder="Type another answer and press Enter",
                            id="interaction-input",
                        )

        def on_mount(self) -> None:
            if isinstance(self.request, ApprovalRequested):
                self.query_one("#allow", Button).focus()
            elif self.request.choices:
                self.query_one("#choice-0", Button).focus()
            else:
                self.query_one("#interaction-input", Input).focus()

        def on_key(self, event: events.Key) -> None:
            if not event.key.isdigit():
                return
            number = int(event.key)
            if isinstance(self.request, ApprovalRequested) and number in {1, 2}:
                self._finish_approval(number == 1)
                event.stop()
            elif isinstance(self.request, QuestionRequested):
                index = number - 1
                if 0 <= index < len(self.request.choices):
                    self._finish_question(self.request.choices[index])
                    event.stop()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            identity = event.button.id or ""
            if isinstance(self.request, ApprovalRequested):
                if identity == "allow":
                    self._finish_approval(True)
                elif identity == "deny":
                    self._finish_approval(False)
                return
            if identity.startswith("choice-"):
                index = int(identity.removeprefix("choice-"))
                self._finish_question(self.request.choices[index])

        def on_input_submitted(self, event: Input.Submitted) -> None:
            answer = event.value.strip()
            if isinstance(self.request, ApprovalRequested):
                self._finish_approval(False)
            elif answer:
                self._finish_question(answer)

        def action_cancel(self) -> None:
            if isinstance(self.request, ApprovalRequested):
                self._finish_approval(False)
            else:
                self._finish_question("")

        def _finish_approval(self, approved: bool) -> None:
            note = self.query_one("#interaction-input", Input).value.strip()
            self.dismiss(
                InteractionReply(
                    self.request.call_id,
                    "approval",
                    approved,
                    "" if approved else note or "Denied by user",
                )
            )

        def _finish_question(self, answer: str) -> None:
            self.dismiss(
                InteractionReply(
                    self.request.request_id,
                    "question",
                    answer,
                    "" if answer else "Cancelled by user",
                )
            )

    class SessionScreen(ModalScreen[str | None]):
        """Searchable full-screen session browser with keyboard-first controls."""

        CSS = """
        SessionScreen { background: #0d0f12; }
        #session-picker { width: 100%; height: 100%; padding: 1 2; }
        #session-picker-title { color: #e6edf3; text-style: bold; margin-bottom: 1; }
        #session-filters { height: 1; margin-bottom: 1; }
        #session-filters Button {
            width: auto; min-width: 0; height: 1; border: none;
            background: #20252d; color: #a7adb8; padding: 0 1; margin-right: 2;
        }
        #session-filters Button:focus { background: #334155; color: #ffffff; text-style: bold; }
        #session-search {
            height: 1; border: none; padding: 0; margin: 0 0 1 0;
            background: #0d0f12;
        }
        #session-options {
            height: 1fr; max-height: 100%; border: none; padding: 0;
            background: #0d0f12; background-tint: transparent;
        }
        #session-options > .option-list--option { padding: 0; }
        #session-options > .option-list--option-highlighted {
            background: #79b8ff; color: #0d0f12; text-style: bold;
        }
        #session-empty { height: auto; color: #a7adb8; margin: 1 0; }
        #session-footer { height: auto; border-top: solid #343a46; color: #a7adb8; padding-top: 1; }
        """
        BINDINGS = [("escape", "cancel", "Back"),
                    Binding("ctrl+a", "archive", "Archive", priority=True)]

        def __init__(self, sessions: Sequence[_SessionChoice], current: str,
                     *, archive: Any = None) -> None:
            super().__init__()
            self.sessions = list(sessions)
            self.current = current
            self.archive = archive
            self.cwd_only = True
            self.show_archived = False
            self.sort_by = "updated_at"
            self.visible_sessions: list[_SessionChoice] = []

        def compose(self) -> ComposeResult:
            with Container(id="session-picker"):
                yield Label("Resume a previous session", id="session-picker-title")
                with Horizontal(id="session-filters"):
                    yield Button("Filter: Cwd", id="session-filter")
                    yield Button("Status: Active", id="session-status")
                    yield Button("Sort: Updated", id="session-sort")
                yield Input(placeholder="Type to search", id="session-search")
                yield OptionList(id="session-options")
                yield Static("No matching sessions. Try another search or filter.", id="session-empty")
                yield Static(id="session-footer")

        def on_mount(self) -> None:
            # Filter toggles should accept consecutive clicks without button debounce.
            for button in self.query("#session-filters Button"):
                button.active_effect_duration = 0
            self._refresh_choices()
            self.query_one("#session-search", Input).focus()

        def _refresh_choices(self) -> None:
            query = self.query_one("#session-search", Input).value.casefold().strip()
            cwd = str(Path.cwd().resolve())
            self.visible_sessions = sorted(
                (choice for choice in self.sessions
                 if choice.archived == self.show_archived
                 and (not self.cwd_only or not choice.cwd or choice.cwd == cwd)
                 and all(word in f"{choice.title} {choice.preview} {choice.session_id}".casefold()
                         for word in query.split())),
                key=lambda choice: (-_timestamp_value(getattr(choice, self.sort_by)),
                                    choice.title.casefold(), choice.session_id),
            )
            options = self.query_one("#session-options", OptionList)
            options.clear_options()
            options.add_options(Option("", id=f"session-{index}")
                                for index in range(len(self.visible_sessions)))
            options.highlighted = 0 if self.visible_sessions else None
            self.query_one("#session-empty").display = not self.visible_sessions
            self._refresh_rows()

        def _refresh_rows(self) -> None:
            options = self.query_one("#session-options", OptionList)
            for index, choice in enumerate(self.visible_sessions):
                options.replace_option_prompt_at_index(index, _session_option(
                    choice, current=self.current, selected=index == options.highlighted,
                    alternate=index % 2 == 1, width=max(30, options.size.width - 2),
                    sort_by=self.sort_by,
                ))
            selected = options.highlighted
            count = len(self.visible_sessions)
            detail = (self.visible_sessions[selected].session_id
                      if selected is not None and selected < count else "No selection")
            archive_hint = "  ctrl+a restore" if self.show_archived else "  ctrl+a archive"
            self.query_one("#session-footer", Static).update(
                f"{(selected + 1) if selected is not None else 0} / {count} · {detail}\n"
                "enter resume  ↑/↓ select  tab focus filters  ←/→ change"
                + (archive_hint if self.archive else "") + "  esc back"
            )

        def on_resize(self) -> None:
            if self.is_mounted:
                self._refresh_rows()

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "session-search":
                self._refresh_choices()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "session-search":
                self._select()

        def on_key(self, event: events.Key) -> None:
            options = self.query_one("#session-options", OptionList)
            if self.focused is self.query_one("#session-search") and event.key in {"up", "down"}:
                if event.key == "down":
                    options.action_cursor_down()
                else:
                    options.action_cursor_up()
                event.prevent_default()
                event.stop()
            elif isinstance(self.focused, Button) and event.key in {"left", "right"}:
                self.focused.press()
                event.stop()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "session-filter":
                self.cwd_only = not self.cwd_only
                event.button.label = "Filter: Cwd" if self.cwd_only else "Filter: All"
            elif event.button.id == "session-status":
                self.show_archived = not self.show_archived
                event.button.label = "Status: Archived" if self.show_archived else "Status: Active"
            elif event.button.id == "session-sort":
                self.sort_by = "created_at" if self.sort_by == "updated_at" else "updated_at"
                event.button.label = "Sort: Created" if self.sort_by == "created_at" else "Sort: Updated"
            self._refresh_choices()

        def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
            if event.option_list.id == "session-options":
                self._refresh_rows()

        def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
            if event.option_list.id == "session-options":
                self._select()

        def _select(self) -> None:
            index = self.query_one("#session-options", OptionList).highlighted
            if index is not None and index < len(self.visible_sessions):
                self.dismiss(self.visible_sessions[index].session_id)

        async def action_archive(self) -> None:
            index = self.query_one("#session-options", OptionList).highlighted
            if self.archive is None or index is None:
                return
            choice = self.visible_sessions[index]
            await await_if_needed(self.archive(choice.session_id, not choice.archived))
            from dataclasses import replace
            self.sessions = [replace(item, archived=not choice.archived)
                             if item.session_id == choice.session_id else item for item in self.sessions]
            self._refresh_choices()

        def action_cancel(self) -> None:
            self.dismiss(None)

    class TuiRenderer:
        """Render normalized events as one continuous terminal transcript."""

        def __init__(
            self,
            transcript: _Transcript,
            scroll: VerticalScroll,
            status: Static,
            *,
            session_id: str,
            title: str = "Harness",
            history: Sequence[Any] = (),
            history_timestamps: Sequence[str | None] = (),
            runtime_info: RuntimeInfo = RuntimeInfo(),
        ) -> None:
            self.transcript = transcript
            self.scroll = scroll
            self.status = status
            self.session_id = session_id
            self.title = title
            self.runtime_info = runtime_info
            self.history = list(history)
            self.history_timestamps = tuple(history_timestamps)
            self.entries: list[Any] = []
            self.activity: list[str] = []
            self.assistant_text = ""
            self.model_calls = 0
            self.usage: dict[str, int] = {}
            self.started_at = time.monotonic()
            self._scope: str | None = None
            self._models: dict[str | None, _ModelState] = {}
            self._responses: dict[int, _ResponseBlock] = {}
            self._answer_drafts: set[int] = set()
            self._entry_parents: dict[int, int] = {}
            self._assistant_index: int | None = None
            self._status_index: int | None = None
            self._thinking_blocks: list[_ThinkingBlock] = []
            self._current_thinking: _ThinkingBlock | None = None
            self._tool_blocks: list[_ToolBlock] = []
            self._tool_blocks_by_id: dict[str, _ToolBlock] = {}
            self._buffer_frame = 0
            self._next_images: tuple[ImageInput, ...] = ()
            self._rebuild_history()
            self._set_status("ready")

        @property
        def _model_state(self) -> _ModelState:
            return self._models.setdefault(self._scope, _ModelState())

        @property
        def _assistant_index(self) -> int | None:
            return self._model_state.response_index

        @_assistant_index.setter
        def _assistant_index(self, value: int | None) -> None:
            self._model_state.response_index = value

        @property
        def _current_thinking(self) -> _ThinkingBlock | None:
            return self._model_state.thinking

        @_current_thinking.setter
        def _current_thinking(self, value: _ThinkingBlock | None) -> None:
            self._model_state.thinking = value

        def _append_entry(self, renderable: Any) -> None:
            parent = self._tool_blocks_by_id.get(self._scope)
            if parent is not None:
                self._entry_parents[len(self.entries)] = parent.index
                if not parent.has_children:
                    parent.has_children = True
                    parent.expanded = True
                    self._update_tool(parent)
            self.entries.append(renderable)

        def _expand_ancestors(self, index: int) -> None:
            tools = {block.index: block for block in self._tool_blocks}
            while index in self._entry_parents:
                index = self._entry_parents[index]
                parent = tools[index]
                parent.expanded = True
                self._update_tool(parent)

        def _collapse_response(self) -> None:
            block = self._responses.get(self._assistant_index)
            if block is not None:
                block.collapsible = True
                self.entries[block.index] = self._response_renderable(block)

        def toggle_response(self, entry_index: int) -> bool:
            block = self._responses.get(entry_index)
            if block is None or not block.collapsible:
                return False
            block.expanded = not block.expanded
            if block.expanded:
                self._expand_ancestors(block.index)
            self.entries[block.index] = self._response_renderable(block)
            self._redraw()
            return True

        def set_session(self, session_id: str, history: Sequence[Any],
                        timestamps: Sequence[str | None] = ()) -> None:
            changed = session_id != self.session_id
            if changed:
                self.model_calls = 0
                self.usage.clear()
            self.session_id = session_id
            self.history = list(history)
            self.history_timestamps = tuple(timestamps)
            self._rebuild_history()
            self._set_status("ready" if changed else self.state)

        def set_history(self, history: Sequence[Any], timestamps: Sequence[str | None] = ()) -> None:
            self.history = list(history)
            self.history_timestamps = tuple(timestamps)
            self._rebuild_history()

        def set_title(self, title: str) -> None:
            self.title = title
            if self.entries:
                heading = Text('>_ ', style='bold cyan')
                heading.append(title, style='bold')
                self.entries[0] = heading
                self._redraw()

        def set_next_images(self, images: Sequence[ImageInput]) -> None:
            self._next_images = tuple(images)

        def clear_screen(self) -> None:
            self.history.clear()
            self._reset_entries()
            self._append_intro()
            self._redraw()

        def note(self, message: str) -> None:
            self._append_activity(f"• {message}", "dim")
            self._redraw()

        def command(self, raw: str) -> None:
            line = Text()
            line.append("⌁ ", style="bold magenta")
            line.append(raw, style="bold magenta")
            self.entries.append(line)
            self._redraw()

        def sheet(self, title: str, rows: Sequence[tuple[str, str]]) -> None:
            block = Text()
            block.append(">_ ", style="bold cyan")
            block.append(title.upper(), style="bold")
            for label, value in rows:
                block.append("\n  ")
                block.append(f"{label.upper():<12}", style="dim cyan")
                block.append(value or "-")
            self.entries.append(block)
            self._redraw()

        def status_sheet(
            self, state: str, sections: Sequence[tuple[str, Sequence[tuple[str, str]]]]
        ) -> None:
            """Show a status snapshot with wrapping values and a clear run state."""
            if state == "failed":
                color = "red"
            elif "waiting" in state or "exhausted" in state:
                color = "yellow"
            elif state in {"ready", "done"}:
                color = "green"
            else:
                color = "cyan"
            content: list[Any] = [Text(state.capitalize(), style=f"bold {color}")]
            for name, rows in sections:
                content.extend((Text(""), Text(name.upper(), style="bold cyan")))
                table = Table.grid(padding=(0, 2), expand=True)
                table.add_column(width=12, style=_DETAIL_STYLE)
                table.add_column(ratio=1, overflow="fold")
                for label, value in rows:
                    table.add_row(Text(label), Text(value or "-"))
                content.append(table)
            self.entries.append(
                Panel(
                    Group(*content),
                    title=Text("Session status", style="bold #c9d1d9"),
                    title_align="left",
                    border_style="#343a46",
                    padding=(1, 2),
                    width=88,
                )
            )
            self._redraw()

        def command_guide(self, extra_sections=()) -> None:
            """Render a categorized, scan-friendly command and shortcut guide."""
            header = Text()
            header.append(">_ ", style="bold cyan")
            header.append("HARNESS COMMAND GUIDE", style="bold")
            intro = Text(
                "Type / for commands or @ for image files. Tab chooses the highlighted result.",
                style="dim",
            )

            commands = Table.grid(padding=(0, 3))
            commands.add_column(width=12, no_wrap=True)
            commands.add_column(width=20, no_wrap=True)
            commands.add_column()
            for section_index, (section, rows) in enumerate((*_HELP_SECTIONS, *extra_sections)):
                if section_index:
                    commands.add_row("", "", "")
                for row_index, (syntax, description) in enumerate(rows):
                    category = Text(section, style="bold magenta") if row_index == 0 else Text("")
                    commands.add_row(
                        category,
                        Text(syntax, style="bold cyan"),
                        Text(description),
                    )

            self.entries.append(Group(header, intro, Text(""), commands))
            self._redraw()

        def animate_thinking(self) -> bool:
            """Advance the active model-call buffer animation."""
            active = [block for block in self._thinking_blocks if block.active]
            if not active:
                return False
            self._buffer_frame = (self._buffer_frame + 1) % len(_BUFFER_FRAMES)
            for block in active:
                block.elapsed = time.monotonic() - block.started_at
                self._update_thinking(block)
            self._redraw()
            return True

        def toggle_thinking(self, entry_index: int | None = None) -> bool:
            """Expand or collapse the newest reasoning trace."""
            if not self._thinking_blocks:
                return False
            block = next(
                (
                    candidate
                    for candidate in self._thinking_blocks
                    if candidate.index == entry_index
                ),
                self._thinking_blocks[-1],
            )
            block.expanded = not block.expanded
            if block.expanded:
                self._expand_ancestors(block.index)
            self._update_thinking(block)
            self._redraw()
            return True

        def toggle_tool(self, entry_index: int | None = None) -> bool:
            """Expand or collapse the newest tool call."""
            if not self._tool_blocks:
                return False
            block = next(
                (candidate for candidate in self._tool_blocks if candidate.index == entry_index),
                self._tool_blocks[-1],
            )
            block.expanded = not block.expanded
            if block.expanded:
                self._expand_ancestors(block.index)
            self._update_tool(block)
            self._redraw()
            return True

        def handle(self, event: RenderEvent) -> None:
            self._scope = event.parent_call_id
            try:
                self._handle(event)
            finally:
                self._scope = None
                self.assistant_text = self._model_state.text

        def _handle(self, event: RenderEvent) -> None:
            if isinstance(event, RunStarted):
                self._answer_drafts.clear()
                if event.prompt is not None:
                    self.started_at = time.monotonic()
                    self._models.clear()
                    self._tool_blocks_by_id.clear()
                    self._model_state.text = ""
                    self.model_calls = 0
                    self.usage.clear()
                    self._assistant_index = None
                    self._status_index = None
                    self._append_user(event.prompt, self._next_images)
                    self._next_images = ()
                else:
                    self._append_activity("• Resuming", "dim cyan")
                self._set_status("working")
            elif isinstance(event, ModelStarted):
                self._collapse_response()
                self.model_calls += 1
                self._model_state.text = ""
                self._assistant_index = None
                self._model_state.tool_drafts.clear()
                self._start_thinking(event.label, event.model)
                self._set_status("thinking")
            elif isinstance(event, TextDelta):
                self._finish_thinking()
                self._model_state.text += event.text
                self._set_assistant(self._model_state.text)
                self._set_status("responding")
            elif isinstance(event, ReasoningDelta):
                if self._current_thinking is None:
                    self._start_thinking("Thinking", None)
                self._current_thinking.content += event.text
                self._update_thinking(self._current_thinking)
            elif isinstance(event, ToolCallDelta):
                self._finish_thinking()
                name, arguments = self._model_state.tool_drafts.get(event.index, ("tool", ""))
                name = event.name or name
                arguments += event.text
                self._model_state.tool_drafts[event.index] = (name, arguments)
                self._set_status(f"preparing {name}")
            elif isinstance(event, ModelFinished):
                if event.replace_answer and self._scope is None:
                    # Preserve activity indexes while replacing every draft from this turn.
                    for index in self._answer_drafts:
                        self.entries[index] = Text('')
                        self._responses.pop(index, None)
                    self._assistant_index = None
                    self._answer_drafts.clear()
                self._finish_thinking(event.reasoning)
                if event.text:
                    self._model_state.text = event.text
                if self._model_state.text:
                    self._set_assistant(
                        self._model_state.text,
                        usage=event.usage,
                        stop_reason=event.stop_reason,
                    )
                if event.requested_tools:
                    self._answer_drafts.discard(self._assistant_index)
                    self._collapse_response()
                for key, value in event.usage.items():
                    self.usage[key] = self.usage.get(key, 0) + value
            elif isinstance(event, ToolStarted):
                self._collapse_response()
                self._finish_thinking()
                self._start_tool(event.call_id, event.name, event.arguments)
                self._set_status(f"running {event.name}")
            elif isinstance(event, ToolProgress):
                suffix = f" {event.progress:.0%}" if event.progress is not None else ""
                block = self._tool_blocks_by_id.get(event.call_id)
                if block is not None:
                    block.progress.append(f"{event.message}{suffix}")
                    self._update_tool(block)
            elif isinstance(event, ToolFinished):
                self._finish_tool(
                    event.call_id,
                    event.name,
                    event.output,
                    event.status,
                )
            elif isinstance(event, ApprovalRequested):
                self._append_activity(
                    f"? {event.name} requires permission",
                    "bold yellow",
                )
                self._set_status("waiting for permission")
            elif isinstance(event, QuestionRequested):
                self._append_activity(f"? {event.question}", "bold yellow")
                self._set_status("waiting for input")
            elif isinstance(event, Notice):
                symbol = {"debug": "·", "info": "•", "warning": "!", "error": "✗"}[event.level]
                self._append_activity(f"{symbol} {event.message}", _notice_style(event.level))
            elif isinstance(event, RunFinished):
                self._finish_thinking()
                if self._scope is not None:
                    self._redraw()
                    return
                elapsed = time.monotonic() - self.started_at
                summary = [f"{elapsed:.1f}s"]
                if self.model_calls:
                    summary.append(f"{self.model_calls} model call(s)")
                if event.pending_count:
                    summary.append(f"{event.pending_count} pending")
                self._append_activity(
                    f"─ {_run_label(event.status)} · {' · '.join(summary)}",
                    "dim",
                )
                self._set_status(_run_label(event.status).lower())
            self._redraw()

        def fail(self, error: BaseException) -> None:
            self._finish_thinking()
            self._append_activity(f"✗ {type(error).__name__}: {error}", "bold red")
            self._set_status("failed")
            self._redraw()

        def close(self) -> None:
            return

        def _rebuild_history(self) -> None:
            self._reset_entries()
            self._append_intro()
            for index, message in enumerate(self.history):
                timestamp = (self.history_timestamps[index]
                             if index < len(self.history_timestamps) else None)
                role = _role(message)
                content = _text(message)
                images = _images(message)
                if role == "user":
                    self._models.clear()
                    self._tool_blocks_by_id.clear()
                    self._append_user(content, images, timestamp=timestamp)
                elif role == "assistant":
                    self._collapse_response()
                    self._assistant_index = None
                    reasoning = getattr(message, "reasoning", None)
                    if reasoning:
                        block = _ThinkingBlock(
                            index=len(self.entries),
                            label="Thought trace",
                            started_at=time.monotonic(),
                            content=str(reasoning),
                            active=False,
                            timestamp=timestamp,
                        )
                        self._thinking_blocks.append(block)
                        self._append_entry(self._thinking_renderable(block))
                    if content:
                        self._set_assistant(
                            content,
                            usage=getattr(message, "usage", {}),
                            stop_reason=getattr(message, "stop_reason", None),
                            timestamp=timestamp,
                        )
                        if getattr(message, "tool_calls", ()):
                            self._collapse_response()
                    for call in getattr(message, "tool_calls", ()):
                        self._start_tool(
                            str(getattr(call, "id", "")),
                            str(getattr(call, "name", "tool")),
                            dict(getattr(call, "arguments", {}) or {}),
                            status="requested",
                            timestamp=timestamp,
                        )
                elif role == "tool":
                    self._finish_tool(
                        str(getattr(message, "call_id", "")),
                        str(getattr(message, "name", "tool")),
                        content,
                        str(getattr(message, "status", "unknown")),
                    )
                elif content:
                    self.entries.append(Text(content, style="dim"))
            self._redraw()

        def _reset_entries(self) -> None:
            self.entries = []
            self._scope = None
            self._models = {}
            self._responses = {}
            self._entry_parents = {}
            self.activity = []
            self.assistant_text = ""
            self._assistant_index = None
            self._status_index = None
            self._thinking_blocks = []
            self._current_thinking = None
            self._tool_blocks = []
            self._tool_blocks_by_id = {}

        def _append_intro(self) -> None:
            title = Text()
            title.append(">_ ", style="bold cyan")
            title.append(self.title, style="bold")
            self.entries.extend(
                [
                    title,
                    Text(
                        _runtime_line(self.runtime_info, self.session_id),
                        style="dim",
                    ),
                    Text(
                        "Type a task · / commands · @ attach a file · Ctrl+V paste an image.",
                        style="dim",
                    ),
                ]
            )

        def _append_user(self, prompt: str, images: Sequence[ImageInput],
                         *, timestamp: str | None = "") -> None:
            line = Text()
            line.append("╭─ you", style="blue")
            line.append("  " + _clock_label(timestamp), style="dim")
            for content_line in (prompt or "[image]").splitlines() or ["[image]"]:
                line.append("\n│ ", style="blue")
                line.append(content_line, style="bright_white")
            if images:
                names = ", ".join(
                    image.filename or f"image {index}"
                    for index, image in enumerate(images, start=1)
                )
                line.append("\n│ ▣ ", style="blue")
                line.append(names, style="cyan")
            line.append("\n╰─", style="blue")
            self.entries.append(Group(Text(""), line, Text("")))

        def _set_assistant(
            self,
            content: str,
            *,
            usage: dict[str, int] | None = None,
            stop_reason: str | None = None,
            timestamp: str | None = "",
        ) -> None:
            if self._assistant_index is None:
                self._assistant_index = len(self.entries)
                block = _ResponseBlock(
                    index=self._assistant_index,
                    content=content,
                    usage=usage,
                    stop_reason=stop_reason,
                    collapsible=self._scope is not None,
                    timestamp=datetime.now().astimezone().isoformat() if timestamp == "" else timestamp,
                )
                self._responses[block.index] = block
                if self._scope is None:
                    self._answer_drafts.add(block.index)
                self._append_entry(self._response_renderable(block))
            else:
                block = self._responses[self._assistant_index]
                block.content = content
                block.usage = usage
                block.stop_reason = stop_reason
                self.entries[block.index] = self._response_renderable(block)

        def _response_renderable(self, block: _ResponseBlock) -> Any:
            if not block.collapsible:
                return self._assistant_renderable(
                    block.content, usage=block.usage, stop_reason=block.stop_reason,
                    timestamp=block.timestamp,
                )
            header = Text(
                ("[−] " if block.expanded else "[+] ") + "response",
                style=Style(color=_DETAIL_COLOR, bold=False, underline=False,
                            meta={"@click": f"app.toggle_response({block.index})"}),
            )
            header.append("  " + _clock_label(block.timestamp), style="dim")
            if not block.expanded:
                return header
            return self._assistant_renderable(
                block.content, stop_reason=block.stop_reason, header=header,
                timestamp=block.timestamp, muted=True,
            )

        def _assistant_renderable(
            self,
            content: str,
            *,
            usage: dict[str, int] | None = None,
            stop_reason: str | None = None,
            header: Text | None = None,
            timestamp: str | None = None,
            muted: bool = False,
        ) -> Group:
            if header is None:
                header = Text("  ─ response", style="dim cyan")
                header.append("  " + _clock_label(timestamp), style="dim")
            body = Padding(
                (_MutedMarkdown if muted else Markdown)(content, code_theme="monokai", hyperlinks=True),
                (0, 0, 1, 2),
            )
            metadata: list[str] = []
            if usage and any(usage.values()):
                counts = normalize_token_usage(usage)
                metadata.extend(
                    (
                        f"{counts['input_tokens']:,} input",
                        f"{counts['output_tokens']:,} output",
                        f"{counts['cache_read_tokens']:,} cached",
                    )
                )
                if counts["cache_write_tokens"]:
                    metadata.append(f"{counts['cache_write_tokens']:,} cache write")
            if stop_reason and stop_reason != "stop":
                metadata.append(stop_reason.replace("_", " "))
            if not metadata:
                return Group(Text(""), header, body)
            return Group(
                Text(""),
                header,
                body,
                Text("  " + " · ".join(metadata), style=_DETAIL_STYLE),
            )

        def _start_thinking(self, label: str, model: str | None) -> None:
            self._finish_thinking()
            detail = label or "Thinking"
            if model:
                detail += f" · {model}"
            block = _ThinkingBlock(
                index=len(self.entries),
                label=detail,
                started_at=time.monotonic(),
            )
            self._thinking_blocks.append(block)
            self._current_thinking = block
            self._status_index = None
            self.activity.append(detail)
            self._append_entry(self._thinking_renderable(block))

        def _finish_thinking(self, reasoning: str | None = None) -> None:
            block = self._current_thinking
            if block is None and reasoning:
                parent = self._tool_blocks_by_id.get(self._scope)
                parent_index = parent.index if parent is not None else None
                block = next((candidate for candidate in reversed(self._thinking_blocks)
                              if self._entry_parents.get(candidate.index) == parent_index), None)
            if block is None:
                return
            if reasoning and not block.content:
                block.content = reasoning
            block.elapsed = max(block.elapsed, time.monotonic() - block.started_at)
            block.active = False
            self._update_thinking(block)
            if self._current_thinking is block:
                self._current_thinking = None
            self._status_index = None

        def _update_thinking(self, block: _ThinkingBlock) -> None:
            if 0 <= block.index < len(self.entries):
                self.entries[block.index] = self._thinking_renderable(block)

        def _thinking_renderable(self, block: _ThinkingBlock) -> Text:
            text = Text(style=_DETAIL_STYLE)
            clickable = Style(
                color=_DETAIL_COLOR,
                bold=False,
                underline=False,
                meta={"@click": f"app.toggle_thinking({block.index})"},
            )
            text.append("[−] " if block.expanded else "[+] ", style=clickable)
            text.append(block.label, style=clickable)
            text.append("  " + _clock_label(block.timestamp), style=_DETAIL_STYLE)
            if block.active:
                text.append(f"  {_BUFFER_FRAMES[self._buffer_frame]}", style=_DETAIL_STYLE)
            text.append(f"  {block.elapsed:.1f}s", style=_DETAIL_STYLE)
            if block.content:
                text.append(f"  · {len(block.content):,} chars", style=_DETAIL_STYLE)
                if not block.expanded:
                    text.append("  · Ctrl+R to expand", style=_DETAIL_STYLE)
            elif not block.active:
                text.append("  · reasoning text not exposed by provider", style=_DETAIL_STYLE)
            if block.expanded:
                content = block.content.strip()
                if not content:
                    content = (
                        "Waiting for reasoning tokens…"
                        if block.active
                        else "The provider returned no visible reasoning text."
                    )
                for line in content.splitlines() or [content]:
                    text.append("\n    ")
                    text.append(line, style=_DETAIL_STYLE)
            return text

        def _start_tool(
            self,
            call_id: str,
            name: str,
            arguments: dict[str, Any],
            *,
            status: str = "running",
            timestamp: str | None = "",
        ) -> _ToolBlock:
            existing = self._tool_blocks_by_id.get(call_id) if call_id else None
            if existing is not None:
                existing.name = name or existing.name
                existing.arguments = arguments or existing.arguments
                existing.status = status
                self._update_tool(existing)
                return existing
            block = _ToolBlock(
                index=len(self.entries),
                call_id=call_id,
                name=name or "tool",
                arguments=dict(arguments),
                status=status,
                timestamp=datetime.now().astimezone().isoformat() if timestamp == "" else timestamp,
            )
            self._tool_blocks.append(block)
            if call_id:
                self._tool_blocks_by_id[call_id] = block
            self.activity.append(f"• Running {block.name}({_arguments(block.arguments)})")
            self._append_entry(self._tool_renderable(block))
            return block

        def _finish_tool(
            self,
            call_id: str,
            name: str,
            output: str,
            status: str,
        ) -> None:
            block = self._tool_blocks_by_id.get(call_id) if call_id else None
            if block is None:
                block = self._start_tool(call_id, name, {}, status=status)
            block.name = name or block.name
            block.output = output
            block.status = status
            symbol = {"completed": "✓", "denied": "⊘", "failed": "✗"}.get(status, "?")
            self.activity.append(f"  {symbol} {block.name} {status}")
            if output:
                self.activity.append(f"    {_limit(output, 4000)}")
            self._update_tool(block)

        def _update_tool(self, block: _ToolBlock) -> None:
            if 0 <= block.index < len(self.entries):
                self.entries[block.index] = self._tool_renderable(block)

        def _tool_renderable(self, block: _ToolBlock, *, include_output: bool = True) -> Text:
            text = Text(style=_DETAIL_STYLE)
            clickable = Style(
                color=_DETAIL_COLOR,
                bold=False,
                underline=False,
                meta={"@click": f"app.toggle_tool({block.index})"},
            )
            symbols = {
                "running": "◌",
                "requested": "○",
                "completed": "✓",
                "denied": "⊘",
                "failed": "✗",
                "unknown": "?",
            }
            text.append("[−] " if block.expanded else "[+] ", style=clickable)
            text.append(" agent " if block.has_children else " tool ",
                        style=Style(color=_DETAIL_COLOR, bold=False,
                                    underline=False, meta=clickable.meta))
            text.append(" " + block.name.replace("_", " "), style=clickable)
            text.append(f"  {symbols.get(block.status, '·')} {block.status}", style=_DETAIL_STYLE)
            text.append("  " + _clock_label(block.timestamp), style=_DETAIL_STYLE)
            if block.arguments and not block.expanded:
                text.append(f"  · {_one_line(_arguments(block.arguments), 100)}", style=_DETAIL_STYLE)
            if not block.expanded:
                text.append("  · Ctrl+T to expand", style=_DETAIL_STYLE)
                return text

            text.append("\n    INPUT", style=_DETAIL_STYLE)
            arguments = json.dumps(
                block.arguments,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            for line in arguments.splitlines():
                text.append("\n      ")
                text.append(line, style=_DETAIL_STYLE)
            if block.progress:
                text.append("\n    PROGRESS", style=_DETAIL_STYLE)
                for update in block.progress:
                    text.append("\n      ")
                    text.append(update, style=_DETAIL_STYLE)
            if block.output and include_output:
                text.append("\n    RESULT", style=_DETAIL_STYLE)
                for line in _limit(block.output, 8000).splitlines():
                    text.append("\n      ")
                    text.append(line, style=_DETAIL_STYLE)
            return text

        def _append_activity(self, message: str, style: str) -> int:
            self.activity.append(message)
            index = len(self.entries)
            self._append_entry(Text(message, style=style))
            return index

        def _replace_status(self, message: str, style: str) -> None:
            if self._status_index is None:
                self._status_index = self._append_activity(message, style)
                return
            self.entries[self._status_index] = Text(message, style=style)
            if self.activity:
                self.activity[-1] = message

        def _set_status(self, value: str) -> None:
            self.state = value
            self.status.update(f"{self.runtime_info.model} · {self.session_id} · {value}")

        def _redraw(self) -> None:
            children: dict[int | None, list[int]] = {}
            for index in range(len(self.entries)):
                children.setdefault(self._entry_parents.get(index), []).append(index)
            tools = {block.index: block for block in self._tool_blocks}

            def render(index: int) -> Any:
                entry = self.entries[index]
                nested = children.get(index, ())
                if nested and tools[index].expanded:
                    block = tools[index]
                    parts = [
                        self._tool_renderable(block, include_output=False),
                        Padding(Group(*(render(child) for child in nested)), (0, 0, 0, 4)),
                    ]
                    if block.output:
                        result = Text("RESULT", style=_DETAIL_STYLE)
                        result.append("\n" + _limit(block.output, 8000), style=_DETAIL_STYLE)
                        parts.append(Padding(result, (0, 0, 0, 4)))
                    return Group(*parts)
                return entry

            self.transcript.update(Group(*(render(index) for index in children.get(None, ()))))
            self.scroll.scroll_end(animate=False)

    class HarnessTui(App[None]):
        """Focused interactive terminal surface for any harness session."""

        command_specs = _COMMANDS
        commands_with_argument = _COMMANDS_WITH_ARGUMENT

        TITLE = "Harness"
        CSS = """
        Screen {
            background: #0d0f12;
            color: #c9d1d9;
        }
        #transcript-scroll {
            height: 1fr;
            padding: 2 4 1 4;
            scrollbar-gutter: stable;
        }
        #transcript {
            width: 100%;
            max-width: 112;
            link-color: #89929d;
            link-color-hover: #b1bac4;
            link-style: none;
            link-style-hover: none;
            link-background-hover: #20252d;
        }
        #attachments {
            display: none;
            height: auto;
            margin: 0 3;
            padding: 0 1;
            color: #79c0ff;
        }
        #command-menu {
            display: none;
            height: auto;
            max-height: 14;
            margin: 0 3;
            padding: 0 1;
            border: solid #343a46;
            background: #111419;
        }
        #composer {
            height: 3;
            margin: 0 3;
            padding: 0 1;
            border: tall #596273;
            background: #111419;
        }
        #composer:focus-within {
            border: tall #8b949e;
        }
        #prompt-prefix {
            width: 2;
            height: 1;
            color: #58a6ff;
            text-style: bold;
        }
        #prompt {
            width: 1fr;
            height: 1;
            padding: 0;
            border: none;
            background: #00000000;
        }
        #meta {
            height: 1;
            margin: 0 4 1 4;
            color: #737b88;
        }
        #status {
            width: 1fr;
        }
        #hint {
            width: auto;
            text-align: right;
        }
        """
        BINDINGS = [
            Binding("ctrl+v", "paste_image", "Paste image", priority=True),
            Binding("ctrl+r", "toggle_thinking", "Toggle thinking", priority=True),
            Binding("ctrl+t", "toggle_tool", "Toggle tool", priority=True),
            ("ctrl+l", "clear_screen", "Clear"),
            ("ctrl+c", "quit", "Quit"),
        ]

        def __init__(
            self,
            session: InteractiveSession | Any,
            *,
            session_id: str,
            title: str = "Harness",
            adapter: Adapter | None = None,
            initial_prompt: str | None = None,
            initial_images: Sequence[ImageInput] = (),
            open_session_picker: bool = False,
        ) -> None:
            super().__init__()
            self.session = _as_interactive_session(session)
            self.session_id = session_id
            self.title = title
            self.adapter = adapter
            self.base_title = title
            self.initial_prompt = initial_prompt
            self.open_session_picker = open_session_picker
            self._attachments = list(initial_images)
            self._busy = False
            self._pending: list[InteractionRequest] = []
            self._visible_commands: list[tuple[str, str]] = []
            self._visible_files: list[Path] = []
            self._menu_mode: Literal["commands", "files"] | None = None
            self._attachment_token_start: int | None = None
            self._known_image_files: tuple[Path, ...] | None = None
            self._suppress_command_menu_once = False
            self.runtime_info = RuntimeInfo()
            self.renderer: TuiRenderer | None = None

        def compose(self) -> ComposeResult:
            with VerticalScroll(id="transcript-scroll"):
                yield _Transcript(id="transcript")
            yield OptionList(id="command-menu", compact=True)
            yield Static(id="attachments")
            with Container(id="composer"):
                with Horizontal():
                    yield Static("›", id="prompt-prefix")
                    yield Input(
                        placeholder="Describe a task or ask a question · @ attach",
                        id="prompt",
                    )
            with Horizontal(id="meta"):
                yield Static(id="status")
                yield Static("/help for commands", id="hint")

        async def on_mount(self) -> None:
            history = await await_if_needed(self.session.history(self.session_id))
            await self._refresh_title()
            self.runtime_info = await self._load_runtime_info()
            self.renderer = TuiRenderer(
                self.query_one("#transcript", _Transcript),
                self.query_one("#transcript-scroll", VerticalScroll),
                self.query_one("#status", Static),
                session_id=self.session_id,
                title=self.title,
                history=history,
                history_timestamps=await self._history_timestamps(),
                runtime_info=self.runtime_info,
            )
            self._refresh_attachments()
            self.query_one("#prompt", Input).focus()
            self.set_interval(0.12, self._animate_thinking)
            if self.initial_prompt is not None or self._attachments:
                payload = PromptInput(self.initial_prompt or "", tuple(self._attachments))
                self._attachments.clear()
                self._refresh_attachments()
                self.call_after_refresh(self.run_turn, payload)
            elif self.open_session_picker:
                self.call_after_refresh(self._resume_session, "")

        def on_input_changed(self, event: Input.Changed) -> None:
            if event.input.id == "prompt":
                if self._suppress_command_menu_once:
                    self._suppress_command_menu_once = False
                    self._hide_command_menu()
                    return
                self._refresh_suggestion_menu(event.value)

        def on_key(self, event: events.Key) -> None:
            prompt = self.query_one("#prompt", Input)
            if (
                event.key == "backspace"
                and prompt.has_focus
                and not prompt.value
                and self._attachments
            ):
                removed = self._attachments.pop()
                self._refresh_attachments()
                self.notify(f"Removed {removed.filename or 'image'}")
                event.prevent_default()
                event.stop()
                return
            menu = self.query_one("#command-menu", OptionList)
            option_count = (
                len(self._visible_commands)
                if self._menu_mode == "commands"
                else len(self._visible_files)
            )
            if not menu.display or not option_count:
                return
            if event.key in {"down", "up"}:
                current = menu.highlighted or 0
                step = 1 if event.key == "down" else -1
                menu.highlighted = (current + step) % option_count
                event.prevent_default()
                event.stop()
            elif event.key == "tab":
                self._complete_highlighted_suggestion()
                event.prevent_default()
                event.stop()

        def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
            if event.option_list.id != "command-menu":
                return
            if self._menu_mode == "files":
                self._choose_attachment_path(self._visible_files[event.option_index])
            else:
                self._complete_command(self._visible_commands[event.option_index][0])

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            value = event.value.strip()
            if self._menu_mode == "files" and self._visible_files:
                self._complete_highlighted_suggestion()
                return
            if value.startswith("/"):
                known = {name for name, _description in self.command_specs}
                if " " not in value and value not in known and self._visible_commands:
                    self._complete_highlighted_suggestion()
                    return
                event.input.value = ""
                self._hide_command_menu()
                await self._command(value)
                return
            if not value and not self._attachments:
                return
            if _attachment_query(event.input.value) is not None:
                self.notify("Choose an image from the @ menu first", severity="warning")
                return
            payload = PromptInput(value, tuple(self._attachments))
            event.input.value = ""
            self._attachments.clear()
            self._refresh_attachments()
            if self._busy:
                try:
                    await await_if_needed(self.session.steer(payload, session_id=self.session_id))
                except Exception as error:  # noqa: BLE001
                    self.notify(str(error), severity="error")
                else:
                    if self.renderer:
                        self.renderer.note("Steering queued")
                return
            self.run_turn(payload)

        async def action_paste_image(self) -> None:
            """Attach an image copied to the OS clipboard."""
            try:
                image = await read_clipboard_image()
            except (ClipboardImageError, ValueError) as error:
                self.notify(str(error), severity="error")
                return
            self._attachments.append(image)
            self._refresh_attachments()
            self.notify("Attached clipboard image")

        def action_toggle_thinking(self, entry_index: int | None = None) -> None:
            if self.renderer and not self.renderer.toggle_thinking(entry_index):
                self.notify("No reasoning trace yet", severity="warning")

        def action_toggle_tool(self, entry_index: int | None = None) -> None:
            if self.renderer and not self.renderer.toggle_tool(entry_index):
                self.notify("No tool call yet", severity="warning")

        def action_toggle_response(self, entry_index: int) -> None:
            if self.renderer:
                self.renderer.toggle_response(entry_index)

        def _animate_thinking(self) -> None:
            if self.renderer:
                self.renderer.animate_thinking()

        @work(exclusive=True, group="harness-turn")
        async def run_turn(self, prompt: PromptInput | str | None) -> None:
            if self.renderer is None:
                return
            payload = normalize_prompt(prompt) if prompt is not None else None
            self._busy = True
            prompt_input = self.query_one("#prompt", Input)
            prompt_input.placeholder = "Send steering while the turn runs · @ attach"
            try:
                history = await await_if_needed(self.session.history(self.session_id))
                self.renderer.set_history(history, await self._history_timestamps())
                await self._consume(payload)
                while self._pending:
                    pending, self._pending = self._pending, []
                    replies = [
                        await self.push_screen_wait(InteractionScreen(request))
                        for request in pending
                    ]
                    await await_if_needed(self.session.respond(replies, session_id=self.session_id))
                    for request, reply in zip(pending, replies, strict=True):
                        self._record_reply(request, reply)
                    await self._consume(None)
            except Exception as error:  # noqa: BLE001
                self.renderer.fail(error)
            finally:
                self._busy = False
                prompt_input.placeholder = "Describe a task or ask a question · @ attach"
                prompt_input.focus()

        async def _consume(self, prompt: PromptInput | None) -> None:
            if prompt is not None and self.renderer:
                self.renderer.set_next_images(prompt.images)
            source = await await_if_needed(self.session.stream(prompt, session_id=self.session_id))
            await render_stream(
                source,
                adapter=self.adapter,
                title=self.title,
                prompt=prompt.text if prompt is not None else None,
                renderer=self.renderer,
                observe=self._capture_interaction,
            )
            await self._refresh_title()

        def _capture_interaction(self, event: RenderEvent) -> None:
            if isinstance(event, (ApprovalRequested, QuestionRequested)):
                self._pending.append(event)

        def _record_reply(
            self,
            request: InteractionRequest,
            reply: InteractionReply,
        ) -> None:
            if not self.renderer:
                return
            if isinstance(request, ApprovalRequested):
                result = "allowed once" if reply.value else f"denied: {reply.message}"
                self.renderer.note(f"{request.name} {result}")
            else:
                self.renderer.note(f"Answered: {reply.value or reply.message}")

        async def _command(self, raw: str) -> None:
            command, _, argument = raw.partition(" ")
            command = command.lower()
            argument = argument.strip()
            if self.renderer and command != "/clear":
                self.renderer.command(raw)
            if command in {"/quit", "/exit", "/q"}:
                self.exit()
            elif command == "/help":
                if self.renderer:
                    self.renderer.command_guide()
            elif command == "/status":
                await self._show_status()
            elif command == "/permissions":
                self._show_permissions()
            elif command == "/rename":
                rename = getattr(self.session, 'rename_session', None)
                if rename is None:
                    self.notify('This harness does not support conversation names.', severity='warning')
                elif self._busy:
                    self.notify('Wait for the current turn to finish.', severity='warning')
                else:
                    try:
                        await await_if_needed(rename(self.session_id, argument))
                        await self._refresh_title()
                    except ValueError as error:
                        self.notify(str(error), severity='error')
            elif command == "/thinking":
                self.action_toggle_thinking()
            elif command == "/tools":
                self.action_toggle_tool()
            elif command == "/clear":
                self.action_clear_screen()
                if self.renderer:
                    self.renderer.command(raw)
            elif command in {"/reload", "/history"}:
                if self._busy:
                    self.notify("Wait for the current turn to finish.", severity="warning")
                else:
                    await self._reload_session()
            elif command == "/resume":
                if self._busy:
                    self.notify("Wait for the current turn to finish.", severity="warning")
                else:
                    await self._resume_session(argument)
            elif command == "/new":
                if self._busy:
                    self.notify("Wait for the current turn to finish.", severity="warning")
                else:
                    await self._new_session(argument)
            else:
                self.notify(f"Unknown command: {command}", severity="warning")

        def _refresh_suggestion_menu(self, value: str) -> None:
            if value.startswith("/"):
                self._refresh_command_menu(value)
                return
            attachment = _attachment_query(value)
            if attachment is not None:
                start, query = attachment
                self._refresh_attachment_menu(start, query)
                return
            self._hide_command_menu()

        def _refresh_command_menu(self, value: str) -> None:
            menu = self.query_one("#command-menu", OptionList)
            if not value.startswith("/") or " " in value:
                self._hide_command_menu()
                return
            prefix = value.lower()
            self._menu_mode = "commands"
            self._visible_files = []
            self._attachment_token_start = None
            self._visible_commands = [item for item in self.command_specs if item[0].startswith(prefix)]
            menu.clear_options()
            for index, (name, description) in enumerate(self._visible_commands):
                prompt = Text()
                prompt.append(name, style="bold cyan")
                prompt.append(f"  {description}", style="dim")
                menu.add_option(Option(prompt, id=f"command-{index}"))
            menu.display = bool(self._visible_commands)
            menu.highlighted = 0 if self._visible_commands else None

        def _refresh_attachment_menu(self, token_start: int, query: str) -> None:
            menu = self.query_one("#command-menu", OptionList)
            self._menu_mode = "files"
            self._visible_commands = []
            self._attachment_token_start = token_start
            self._visible_files = self._attachment_candidates(query)
            menu.clear_options()
            for index, path in enumerate(self._visible_files):
                prompt = Text()
                prompt.append("@ ", style="bold magenta")
                display = _display_path(path)
                if path.is_dir():
                    prompt.append(display.rstrip("/") + "/", style="bold cyan")
                    prompt.append("  directory", style="dim magenta")
                else:
                    prompt.append(display, style="bold cyan")
                    try:
                        prompt.append(f"  {_file_size(path.stat().st_size)}", style="dim")
                    except OSError:
                        pass
                menu.add_option(Option(prompt, id=f"file-{index}"))
            menu.display = bool(self._visible_files)
            menu.highlighted = 0 if self._visible_files else None

        def _attachment_candidates(self, query: str) -> list[Path]:
            visible = _browse_attachment_candidates(query)
            if "/" in query or query.startswith("~") or not query:
                return visible[:20]
            if self._known_image_files is None:
                self._known_image_files = _discover_image_files(Path.cwd())
            needle = query.lower().removeprefix("./")
            seen = {path.resolve() for path in visible}
            ranked: list[tuple[int, int, str, Path]] = [
                (0, index, _display_path(path).lower(), path) for index, path in enumerate(visible)
            ]
            for path in self._known_image_files:
                if path in seen:
                    continue
                display = _display_path(path).lower()
                name = path.name.lower()
                if needle and needle not in display:
                    continue
                rank = 2 if display.startswith(needle) else 3 if name.startswith(needle) else 4
                ranked.append((rank, len(display), display, path))
            ranked.sort(key=lambda item: item[:3])
            return [item[3] for item in ranked[:20]]

        def _hide_command_menu(self) -> None:
            menu = self.query_one("#command-menu", OptionList)
            menu.display = False
            self._visible_commands = []
            self._visible_files = []
            self._menu_mode = None
            self._attachment_token_start = None

        def _complete_highlighted_suggestion(self) -> None:
            menu = self.query_one("#command-menu", OptionList)
            index = menu.highlighted or 0
            if self._menu_mode == "files" and index < len(self._visible_files):
                self._choose_attachment_path(self._visible_files[index])
            elif self._visible_commands and index < len(self._visible_commands):
                self._complete_command(self._visible_commands[index][0])

        def _complete_command(self, command: str) -> None:
            prompt = self.query_one("#prompt", Input)
            self._suppress_command_menu_once = True
            prompt.value = command + (" " if command in self.commands_with_argument else "")
            prompt.cursor_position = len(prompt.value)
            self._hide_command_menu()
            prompt.focus()

        def _choose_attachment_path(self, path: Path) -> None:
            if path.is_dir():
                self._open_attachment_directory(path)
            else:
                self._attach_file(path)

        def _open_attachment_directory(self, path: Path) -> None:
            prompt = self.query_one("#prompt", Input)
            token_start = self._attachment_token_start
            prefix = prompt.value[:token_start] if token_start is not None else ""
            directory = _display_path(path).rstrip("/") + "/"
            prompt.value = f"{prefix}@{directory}"
            prompt.cursor_position = len(prompt.value)
            self._refresh_suggestion_menu(prompt.value)
            prompt.focus()

        def _attach_file(self, path: Path) -> None:
            try:
                image = ImageInput.from_path(path)
            except ValueError as error:
                self.notify(str(error), severity="error")
                return
            prompt = self.query_one("#prompt", Input)
            token_start = self._attachment_token_start
            remaining = (
                prompt.value[:token_start].rstrip() if token_start is not None else prompt.value
            )
            self._attachments.append(image)
            self._suppress_command_menu_once = True
            prompt.value = remaining
            prompt.cursor_position = len(remaining)
            self._hide_command_menu()
            self._refresh_attachments()
            self.notify(f"Attached {image.filename}")
            prompt.focus()

        def _refresh_attachments(self) -> None:
            widget = self.query_one("#attachments", Static)
            if not self._attachments:
                widget.display = False
                widget.update("")
                return
            count = len(self._attachments)
            noun = "image" if count == 1 else "images"
            widget.update(
                f"▣ NEXT MESSAGE · {count} {noun} attached · "
                + _attachment_summary(self._attachments)
            )
            widget.display = True

        def _note(self, message: str) -> None:
            if self.renderer:
                self.renderer.note(message)

        def action_clear_screen(self) -> None:
            if self.renderer:
                self.renderer.clear_screen()

        async def _reload_session(self) -> None:
            history = await await_if_needed(self.session.history(self.session_id))
            await self._refresh_title()
            if self.renderer:
                self.renderer.set_session(self.session_id, history, await self._history_timestamps())

        async def _history_timestamps(self) -> Sequence[str | None]:
            read = getattr(self.session, "history_timestamps", None)
            return await await_if_needed(read(self.session_id)) if read else ()

        async def _conversation_title(self, session_id: str) -> str:
            read = getattr(self.session, 'session_title', None)
            if read:
                return await await_if_needed(read(session_id))
            history = await await_if_needed(self.session.history(session_id))
            return conversation_title(history)

        async def _refresh_title(self) -> None:
            name = await self._conversation_title(self.session_id)
            self.title = f'{self.base_title} · {name}' if name else self.base_title
            if self.renderer:
                self.renderer.set_title(self.title)

        async def _load_runtime_info(self) -> RuntimeInfo:
            describe = getattr(self.session, "runtime_info", None)
            if describe is None:
                return RuntimeInfo()
            return await await_if_needed(describe(self.session_id))

        async def _show_status(self) -> None:
            self.runtime_info = await self._load_runtime_info()
            history = tuple(await await_if_needed(self.session.history(self.session_id)))
            sessions = tuple(await await_if_needed(self.session.sessions()))
            attachments = f"{len(self._attachments)} for next message" if self._attachments else "none"
            route = self.runtime_info.provider
            if self.runtime_info.api:
                route += f" · {self.runtime_info.api}"
            tools = self.runtime_info.tool_names
            tool_summary = (
                f"{len(tools)} · {', '.join(tools[:4])}" + ("…" if len(tools) > 4 else "")
                if tools
                else "none advertised"
            )
            if self.renderer:
                self.renderer.runtime_info = self.runtime_info
                message_noun = "message" if len(history) == 1 else "messages"
                session_noun = "session" if len(sessions) == 1 else "sessions"
                state = self.renderer.state
                if self._busy and state in {"ready", "done"}:
                    state = "working"
                usage = normalize_token_usage(self.renderer.usage) if self.renderer.usage else None
                tokens = (
                    f"{usage['input_tokens']:,} input · {usage['output_tokens']:,} output"
                    + (f" · {usage['cache_read_tokens']:,} cached" if usage["cache_read_tokens"] else "")
                    if usage
                    else "Not reported"
                )
                self.renderer.status_sheet(
                    state,
                    (
                        (
                            "Model",
                            (
                                ("Model", self.runtime_info.model),
                                ("Provider", route),
                                ("Features", ", ".join(self.runtime_info.capabilities) or "Not reported"),
                                ("Permissions", self.runtime_info.permission_policy),
                            ),
                        ),
                        (
                            "Session",
                            (
                                (
                                    "Conversation",
                                    await self._conversation_title(self.session_id) or self.session_id,
                                ),
                                ("Session ID", self.session_id),
                                (
                                    "History",
                                    f"{len(history)} {message_noun} · {len(sessions)} saved {session_noun}",
                                ),
                                ("Images", attachments),
                            ),
                        ),
                        (
                            "Workspace",
                            (
                                ("Directory", str(Path.cwd())),
                                ("Storage", self.runtime_info.storage or "Harness-owned"),
                                ("Tools", tool_summary),
                            ),
                        ),
                        (
                            "Latest turn · this client",
                            (
                                ("Model calls", str(self.renderer.model_calls)),
                                ("Tokens", tokens),
                                ("Pending", str(len(self._pending))),
                            ),
                        ),
                    ),
                )

        def _show_permissions(self) -> None:
            if self.renderer:
                tools = self.runtime_info.tool_names
                tool_summary = ", ".join(tools) if tools else "none advertised"
                self.renderer.sheet(
                    "permission boundary",
                    (
                        ("policy", self.runtime_info.permission_policy),
                        ("tools", tool_summary),
                        ("pending", str(len(self._pending))),
                        ("decision", "Allow once or deny with a reason"),
                        ("scope", "An approval applies only to its tool-call id"),
                        ("execution", "Denied calls return a tool result; they do not run"),
                    ),
                )

        async def _resume_session(self, session_id: str) -> None:
            sessions = tuple(await await_if_needed(self.session.sessions()))
            if session_id:
                if session_id not in sessions:
                    self.notify(f"Unknown session: {session_id}", severity="error")
                    return
                await self._switch_existing_session(session_id)
                return
            if not sessions:
                self.notify("No saved sessions", severity="warning")
                return
            details = getattr(self.session, "session_details", None)
            metadata = {item.session_id: item for item in
                        (await await_if_needed(details()) if details else ())}
            choices = []
            for candidate in sessions:
                history = tuple(await await_if_needed(self.session.history(candidate)))
                info = metadata.get(candidate, SessionInfo(candidate))
                choices.append(_SessionChoice(
                    candidate, len(history), _history_preview(history),
                    info.title or await self._conversation_title(candidate) or conversation_title(history),
                    info.created_at, info.updated_at, info.cwd, info.archived,
                ))
            self.push_screen(
                SessionScreen(choices, self.session_id,
                              archive=getattr(self.session, "archive_session", None)),
                self._resume_session_selected,
            )

        def _resume_session_selected(self, session_id: str | None) -> None:
            if session_id is not None:
                self.run_worker(self._switch_existing_session(session_id), group="session")

        async def _switch_existing_session(self, session_id: str) -> None:
            self.session_id = session_id
            self.runtime_info = await self._load_runtime_info()
            if self.renderer:
                self.renderer.runtime_info = self.runtime_info
            await self._reload_session()

        async def _new_session(self, session_id: str = "") -> None:
            sessions = set(await await_if_needed(self.session.sessions()))
            session_id = session_id or f"session-{uuid4().hex[:12]}"
            if session_id in sessions or session_id == self.session_id:
                self.notify("That session already exists. Use /resume to open it.", severity="warning")
                return
            try:
                await await_if_needed(self.session.create_session(session_id))
            except ValueError as error:
                self.notify(str(error), severity="error")
                return
            self._attachments.clear()
            self._pending.clear()
            self._refresh_attachments()
            self.query_one("#prompt", Input).value = ""
            self._hide_command_menu()
            await self._switch_existing_session(session_id)
            self.query_one("#prompt", Input).focus()


else:

    class TuiRenderer:  # pragma: no cover
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _require_textual()

    class HarnessTui:  # pragma: no cover
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _require_textual()



def _require_textual() -> None:
    raise RuntimeError("The TUI requires Textual. Install dependencies with `uv sync --extra terminal`.")


def _as_interactive_session(value: Any) -> InteractiveSession:
    if all(
        hasattr(value, name)
        for name in ("stream", "respond", "steer", "history", "sessions", "create_session")
    ):
        return value
    if all(hasattr(value, name) for name in ("run_stream", "model", "tools")):
        return AgentSession(value)
    raise TypeError(
        "run_tui expects an Agent or InteractiveSession; use HarnessBinding for another runtime"
    )


def _arguments(arguments: dict[str, Any]) -> str:
    return ", ".join(
        f"{key}={json.dumps(value, ensure_ascii=False, default=str)}"
        for key, value in arguments.items()
    )


def _attachment_query(value: str) -> tuple[int, str] | None:
    """Return the trailing @ token used by the file attachment picker."""
    if value.startswith("@"):
        start = 0
    else:
        marker = value.rfind(" @")
        if marker < 0:
            return None
        start = marker + 1
    query = value[start + 1 :]
    if any(character.isspace() for character in query):
        return None
    return start, query


def _discover_image_files(root: Path, *, limit: int = 2000) -> tuple[Path, ...]:
    """Discover attachable images without walking generated or private trees."""
    found: list[Path] = []
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in _IGNORED_ATTACHMENT_DIRS and not name.startswith(".")
        ]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if path.suffix.lower() in _IMAGE_SUFFIXES:
                found.append(path.resolve())
                if len(found) >= limit:
                    return tuple(found)
    return tuple(found)


def _browse_attachment_candidates(query: str) -> list[Path]:
    """List child directories and supported images for the typed path."""
    typed = Path(query).expanduser()
    typed = typed if typed.is_absolute() else Path.cwd() / typed
    if query.endswith("/"):
        directory, prefix = typed, ""
    elif "/" not in query and not query.startswith("~"):
        directory, prefix = Path.cwd(), query.lower()
    else:
        directory, prefix = typed.parent, typed.name.lower()
    if not directory.is_dir():
        return []
    try:
        candidates = [
            path.resolve()
            for path in directory.iterdir()
            if (
                (
                    path.is_dir()
                    and path.name not in _IGNORED_ATTACHMENT_DIRS
                    and not path.name.startswith(".")
                )
                or (path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)
            )
            and path.name.lower().startswith(prefix)
        ]
    except OSError:
        return []
    return sorted(candidates, key=lambda path: (not path.is_dir(), path.name.lower()))


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def _file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _approval_detail(request: ApprovalRequested) -> str:
    parts = [request.reason] if request.reason else []
    if request.arguments:
        parts.append(json.dumps(request.arguments, ensure_ascii=False, indent=2, default=str))
    return "\n\n".join(parts)


def _attachment_summary(images: Sequence[ImageInput]) -> str:
    return " · ".join(
        f"{index}. {image.filename or 'remote image'}"
        for index, image in enumerate(images, start=1)
    )


def _clock_label(value: str | None) -> str:
    if value == "":
        stamp = datetime.now().astimezone()
    elif not value:
        return "time unavailable"
    else:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except (ValueError, TypeError):
            return "time unavailable"
    day = stamp.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {stamp.strftime('%B %y, %H:%M')}"


def _timestamp_value(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _relative_time(value: str | None) -> str:
    timestamp = _timestamp_value(value)
    if not timestamp:
        return "-"
    seconds = max(0, int(time.time() - timestamp))
    for divisor, suffix in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= divisor:
            return f"{seconds // divisor}{suffix} ago"
    return f"{seconds}s ago"


def _session_option(choice: _SessionChoice, *, current: str, selected: bool = False,
                    alternate: bool = False, width: int = 100,
                    sort_by: str = "updated_at") -> Text:
    age = _relative_time(getattr(choice, sort_by))
    marker = "›" if selected else " "
    title = choice.title or choice.preview or "New conversation"
    suffix = " · current" if choice.session_id == current else ""
    line = f"{marker} {age:<10} {title}{suffix}"
    line = _limit(line, width).ljust(width)
    style = ("bold #0d0f12 on #79b8ff" if selected else
             "#a5d6cf on #16191e" if alternate else "#a5d6cf on #0d0f12")
    return Text(line, style=style, no_wrap=True, overflow="ellipsis")


def _history_preview(history: Sequence[Any]) -> str:
    for message in reversed(history):
        content = _one_line(_text(message), 56)
        if content:
            return content
        images = _images(message)
        if images:
            return f"{len(images)} image attachment(s)"
    return "empty session"


def _runtime_line(info: RuntimeInfo, session_id: str) -> str:
    route = info.provider
    if info.api:
        route += f"/{info.api}"
    return f"{info.model} · {route} · session {session_id}"


def _limit(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _one_line(value: str, limit: int) -> str:
    return _limit(" ".join(value.split()), limit)


def _notice_style(level: str) -> str:
    return {
        "debug": "dim",
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
    }.get(level, "dim")


def _run_label(status: str) -> str:
    return {
        "completed": "Done",
        "waiting_for_approval": "Waiting for permission",
        "waiting_for_input": "Waiting for input",
        "budget_exhausted": "Model-call budget exhausted",
        "failed": "Failed",
    }.get(status, status)


async def run_tui(
    session: InteractiveSession | Any,
    *,
    session_id: str = "default",
    title: str = "Harness",
    adapter: Adapter | None = None,
    initial_prompt: str | None = None,
    initial_images: Sequence[ImageInput] = (),
    open_session_picker: bool = False,
) -> None:
    """Run the interactive terminal UI until the user exits."""
    if not TEXTUAL_AVAILABLE:
        _require_textual()
    app = HarnessTui(
        session,
        session_id=session_id,
        title=title,
        adapter=adapter,
        initial_prompt=initial_prompt,
        initial_images=initial_images,
        open_session_picker=open_session_picker,
    )
    await app.run_async()
