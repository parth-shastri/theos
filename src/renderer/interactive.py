"""Framework-neutral session boundary for the interactive terminal UI."""

from __future__ import annotations

import asyncio
import inspect
from contextlib import aclosing
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from renderer.events import ApprovalRequested, QuestionRequested

from harness import ImageInput

type EventSource = AsyncIterable[Any] | Iterable[Any]
type MaybeAwaitable[T] = T | Awaitable[T]
type InteractionRequest = ApprovalRequested | QuestionRequested


@dataclass(frozen=True)
class PromptInput:
    """One interactive user turn, including zero or more image inputs."""

    text: str = ""
    images: tuple[ImageInput, ...] = ()


@dataclass(frozen=True)
class RuntimeInfo:
    """Stable runtime facts the TUI may display without owning the harness."""

    model: str = "unknown"
    provider: str = "unknown"
    api: str | None = None
    capabilities: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    permission_policy: str = "Harness-defined"
    storage: str | None = None


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    title: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    cwd: str | None = None
    archived: bool = False


def normalize_prompt(value: PromptInput | str) -> PromptInput:
    """Preserve compatibility with text-only session callers."""
    return value if isinstance(value, PromptInput) else PromptInput(value)


@dataclass(frozen=True)
class InteractionReply:
    """The user's answer to a permission or question event."""

    request_id: str
    kind: Literal["approval", "question"]
    value: bool | str
    message: str = ""


@runtime_checkable
class InteractiveSession(Protocol):
    """The small interface needed by :class:`HarnessTui`.

    ``stream(None, ...)`` resumes work after replies have been recorded.
    Methods other than ``stream`` may be synchronous or asynchronous; the TUI
    normalizes both forms. Session and persistence behavior remain owned by the
    harness adapter.
    """

    def stream(
        self, prompt: PromptInput | str | None, *, session_id: str
    ) -> MaybeAwaitable[EventSource]: ...

    def respond(
        self, replies: Sequence[InteractionReply], *, session_id: str
    ) -> MaybeAwaitable[None]: ...

    def steer(self, prompt: PromptInput | str, *, session_id: str) -> MaybeAwaitable[None]: ...

    def history(self, session_id: str) -> MaybeAwaitable[Sequence[Any]]: ...

    def sessions(self) -> MaybeAwaitable[Sequence[str]]: ...

    def create_session(self, session_id: str) -> MaybeAwaitable[None]: ...


@dataclass
class HarnessBinding:
    """Build an interactive harness adapter from ordinary callables.

    Only ``run`` is required. Omitted capabilities degrade cleanly: history is
    empty, the configured session is the only listed session, and attempts to
    answer an interaction raise a useful error.
    """

    run: Callable[[PromptInput | str | None, str], MaybeAwaitable[EventSource]]
    on_respond: Callable[[Sequence[InteractionReply], str], MaybeAwaitable[None]] | None = None
    on_steer: Callable[[PromptInput | str, str], MaybeAwaitable[None]] | None = None
    load_history: Callable[[str], MaybeAwaitable[Sequence[Any]]] | None = None
    list_sessions: Callable[[], MaybeAwaitable[Sequence[str]]] | None = None
    ensure_session: Callable[[str], MaybeAwaitable[None]] | None = None
    describe_runtime: Callable[[str], MaybeAwaitable[RuntimeInfo]] | None = None
    default_session_id: str = "default"
    list_session_details: Callable[[], MaybeAwaitable[Sequence[SessionInfo]]] | None = None
    load_timestamps: Callable[[str], MaybeAwaitable[Sequence[str | None]]] | None = None

    def stream(
        self, prompt: PromptInput | str | None, *, session_id: str
    ) -> MaybeAwaitable[EventSource]:
        return self.run(prompt, session_id)

    def respond(
        self, replies: Sequence[InteractionReply], *, session_id: str
    ) -> MaybeAwaitable[None]:
        if self.on_respond is None:
            raise RuntimeError("this harness did not configure interaction replies")
        return self.on_respond(replies, session_id)

    def steer(self, prompt: PromptInput | str, *, session_id: str) -> MaybeAwaitable[None]:
        if self.on_steer is None:
            raise RuntimeError("this harness does not accept steering while it runs")
        return self.on_steer(prompt, session_id)

    def history(self, session_id: str) -> MaybeAwaitable[Sequence[Any]]:
        if self.load_history is None:
            return ()
        return self.load_history(session_id)

    def sessions(self) -> MaybeAwaitable[Sequence[str]]:
        if self.list_sessions is None:
            return (self.default_session_id,)
        return self.list_sessions()

    def create_session(self, session_id: str) -> MaybeAwaitable[None]:
        if self.ensure_session is None:
            return None
        return self.ensure_session(session_id)

    def session_details(self) -> MaybeAwaitable[Sequence[SessionInfo]]:
        return self.list_session_details() if self.list_session_details else ()

    def history_timestamps(self, session_id: str) -> MaybeAwaitable[Sequence[str | None]]:
        return self.load_timestamps(session_id) if self.load_timestamps else ()

    def runtime_info(self, session_id: str) -> MaybeAwaitable[RuntimeInfo]:
        if self.describe_runtime is None:
            return RuntimeInfo()
        return self.describe_runtime(session_id)


@dataclass
class AgentSession:
    """Persistent interactive sessions for the local ``harness.Agent``.

    This is the ready-made adapter for the harness in this repository. Custom
    runtimes can implement :class:`InteractiveSession` directly or use
    :class:`HarnessBinding`.
    """

    agent: Any
    store: Any = None
    deps: Any | Callable[[str], Any | Awaitable[Any]] = None
    budget_factory: Callable[[], Any] | None = None
    _inboxes: dict[str, Any] = field(default_factory=dict, init=False)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict, init=False)
    _known_sessions: set[str] = field(default_factory=lambda: {"default"}, init=False)

    _states: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        if self.store is None:
            from harness import MemoryStore

            self.store = MemoryStore()

    def _inbox(self, session_id: str) -> Any:
        from harness import Inbox

        return self._inboxes.setdefault(session_id, Inbox())

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def _deps(self, session_id: str) -> Any:
        value = self.deps(session_id) if callable(self.deps) else self.deps
        return await value if inspect.isawaitable(value) else value

    async def _state(self, session_id: str) -> dict[str, Any]:
        if session_id not in self._states:
            load = getattr(self.store, "load_state", None)
            self._states[session_id] = await await_if_needed(load(session_id)) if load else {}
        return self._states[session_id]

    async def _save_state(self, session_id: str) -> None:
        save = getattr(self.store, "save_state", None)
        if save:
            await await_if_needed(save(session_id, self._states[session_id]))

    async def stream(
        self, prompt: PromptInput | str | None, *, session_id: str
    ) -> AsyncIterable[Any]:
        from harness import Budget, ContextMemory, UserMessage
        from harness.titles import conversation_title

        self._known_sessions.add(session_id)
        async with self._lock(session_id):
            history = await self.store.load(session_id) or []
            state = await self._state(session_id)
            now = datetime.now().astimezone().isoformat()
            state.setdefault("created_at", now)
            state.setdefault("cwd", str(Path.cwd().resolve()))
            saved_times = state.get("timestamps", [])
            times = [saved_times[i] if i < len(saved_times) else None for i in range(len(history))]
            state["timestamps"] = times
            memory = ContextMemory.from_dict(state.get("memory"))
            if prompt is not None:
                payload = normalize_prompt(prompt)
                history.append(UserMessage(payload.text, list(payload.images)))
                times.append(now)
                await self.store.save(session_id, history)
                state["updated_at"] = now
                await self._save_state(session_id)
            budget = self.budget_factory() if self.budget_factory else Budget(10)
            try:
                async with aclosing(self.agent.run_stream(
                    history,
                    deps=await self._deps(session_id),
                    inbox=self._inbox(session_id),
                    budget=budget,
                    memory=memory,
                )) as events:
                    async for event in events:
                        times.extend([datetime.now().astimezone().isoformat()] * (len(history) - len(times)))
                        yield event
            finally:
                now = datetime.now().astimezone().isoformat()
                times.extend([now] * (len(history) - len(times)))
                state["updated_at"] = now
                state["memory"] = memory.to_dict()
                if state.get("title_source") != "manual":
                    state["title"] = conversation_title(history)
                await self.store.save(session_id, history)
                await self._save_state(session_id)

    async def respond(self, replies: Sequence[InteractionReply], *, session_id: str) -> None:
        from harness import UserMessage

        inbox = self._inbox(session_id)
        for reply in replies:
            if reply.kind == "approval":
                inbox.resolve(
                    reply.request_id,
                    approved=bool(reply.value),
                    reason=reply.message,
                )
            else:
                inbox.steer(UserMessage(str(reply.value)))

    def steer(self, prompt: PromptInput | str, *, session_id: str) -> None:
        from harness import UserMessage

        payload = normalize_prompt(prompt)
        self._inbox(session_id).steer(UserMessage(payload.text, list(payload.images)))

    async def history(self, session_id: str) -> Sequence[Any]:
        self._known_sessions.add(session_id)
        return await self.store.load(session_id) or ()

    async def sessions(self) -> Sequence[str]:
        keys = getattr(self.store, "keys", None)
        if keys is not None:
            stored = keys()
            stored = await stored if inspect.isawaitable(stored) else stored
            self._known_sessions.update(stored)
        return tuple(sorted(self._known_sessions))

    async def create_session(self, session_id: str) -> None:
        async with self._lock(session_id):
            self._known_sessions.add(session_id)
            if await self.store.load(session_id) is None:
                await self.store.save(session_id, ())
                now = datetime.now().astimezone().isoformat()
                self._states[session_id] = dict(
                    created_at=now, updated_at=now, cwd=str(Path.cwd().resolve()),
                    title="New conversation", timestamps=[], archived=False,
                )
                await self._save_state(session_id)

    async def history_timestamps(self, session_id: str) -> Sequence[str | None]:
        return (await self._state(session_id)).get("timestamps", ())

    async def session_title(self, session_id: str) -> str:
        from harness.titles import conversation_title

        state = await self._state(session_id)
        return state.get("title") or conversation_title(await self.history(session_id))

    async def session_details(self) -> Sequence[SessionInfo]:
        details = []
        for session_id in await self.sessions():
            state = await self._state(session_id)
            details.append(SessionInfo(
                session_id, await self.session_title(session_id), state.get("created_at"),
                state.get("updated_at"), state.get("cwd"), bool(state.get("archived")),
            ))
        return tuple(details)

    async def rename_session(self, session_id: str, title: str) -> None:
        async with self._lock(session_id):
            state = await self._state(session_id)
            state.update(title=title.strip(), title_source="manual")
            await self._save_state(session_id)

    async def archive_session(self, session_id: str, archived: bool) -> None:
        async with self._lock(session_id):
            state = await self._state(session_id)
            state["archived"] = archived
            await self._save_state(session_id)

    def runtime_info(self, session_id: str) -> RuntimeInfo:
        return _agent_runtime_info(self.agent, self.store)


def _agent_runtime_info(agent: Any, storage: Any) -> RuntimeInfo:
    model = agent.model
    capabilities = getattr(model, "capabilities", None)
    enabled = tuple(
        label
        for attribute, label in (
            ("vision", "vision"),
            ("tools", "tools"),
            ("parallel_tool_calls", "parallel tools"),
            ("json_schema_output", "structured output"),
            ("reasoning", "reasoning"),
        )
        if bool(getattr(capabilities, attribute, False))
    )
    before_tool = getattr(getattr(agent, "hooks", None), "before_tool", None)
    automatic = getattr(before_tool, "__name__", "") == "allow_all"
    storage_path = getattr(storage, "path", None)
    return RuntimeInfo(
        model=str(getattr(model, "model_id", type(model).__name__)),
        provider=str(getattr(model, "provider", type(model).__name__)),
        api=getattr(model, "api", None),
        capabilities=enabled,
        tool_names=tuple(tool.name for tool in getattr(agent, "tools", ())),
        permission_policy=(
            "Automatic; no pre-tool approval hook"
            if automatic
            else "Pre-tool policy hook may ask, allow, or deny"
        ),
        storage=str(storage_path) if storage_path is not None else type(storage).__name__,
    )


async def await_if_needed[T](value: MaybeAwaitable[T]) -> T:
    """Await a value only when an adapter returned an awaitable."""
    return await value if inspect.isawaitable(value) else value


__all__ = [
    "AgentSession",
    "EventSource",
    "HarnessBinding",
    "InteractionReply",
    "InteractionRequest",
    "InteractiveSession",
    "PromptInput",
    "RuntimeInfo",
    "SessionInfo",
    "await_if_needed",
    "normalize_prompt",
]
