"""Framework-neutral stream orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Iterable, Iterator
from typing import Any, Protocol

from renderer.adapters import Adapter, AutoAdapter, events
from renderer.events import RenderEvent, RunFinished, RunStarted

_END = object()


class Renderer(Protocol):
    """Minimal interface implemented by any renderer backend."""

    def handle(self, event: RenderEvent) -> None: ...

    def fail(self, error: BaseException) -> None: ...

    def close(self) -> None: ...


class CompositeRenderer:
    """Fan each normalized event out to multiple renderer backends."""

    def __init__(self, *renderers: Renderer) -> None:
        self.renderers = renderers

    def handle(self, event: RenderEvent) -> None:
        for renderer in self.renderers:
            renderer.handle(event)

    def fail(self, error: BaseException) -> None:
        for renderer in self.renderers:
            renderer.fail(error)

    def close(self) -> None:
        for renderer in reversed(self.renderers):
            renderer.close()


def make_event_handler(
    renderer: Renderer,
    *,
    adapter: Adapter | None = None,
    observe: Callable[[RenderEvent], None] | None = None,
) -> Callable[[Any], None]:
    """Adapt push/callback-style framework events into a renderer."""
    normalize = adapter or AutoAdapter()

    def handle(raw: Any) -> None:
        for event in events(normalize(raw)):
            renderer.handle(event)
            if observe is not None:
                observe(event)

    return handle


async def render_stream(
    source: AsyncIterable[Any] | Iterable[Any],
    *,
    adapter: Adapter | None = None,
    renderer: Renderer | None = None,
    title: str = "Agent",
    prompt: str | None = None,
    observe: Callable[[RenderEvent], None] | None = None,
    on_raw_event: Callable[[Any], None] | None = None,
) -> Any:
    """Render any sync or async agent stream through one tiny adapter.

    The adapter may return one normalized event, several events, or ``None``.
    When omitted, ``AutoAdapter`` recognizes this harness, LangGraph stream
    shapes, smolagents steps, strings, and objects with a ``content`` field.
    """
    if renderer is None:
        from renderer.terminal import TerminalRenderer

        renderer = TerminalRenderer()
    normalize = adapter or AutoAdapter()

    def emit(event: RenderEvent) -> None:
        renderer.handle(event)
        if observe is not None:
            observe(event)

    emit(RunStarted(title, prompt))
    result: Any = None
    last_raw: Any = None
    finished = False

    try:
        async for raw in _iterate(source):
            last_raw = raw
            for event in events(normalize(raw)):
                if isinstance(event, RunFinished) and event.parent_call_id is None:
                    if finished:
                        raise RuntimeError("stream produced more than one final event")
                    result = event.result
                    finished = True
                emit(event)
            if on_raw_event is not None:
                on_raw_event(raw)
        if not finished:
            result = last_raw
            emit(RunFinished("completed", result))
        return result
    except Exception as error:
        renderer.fail(error)
        raise
    finally:
        renderer.close()


async def _iterate(source: AsyncIterable[Any] | Iterable[Any]):
    """Iterate async streams directly and blocking generators in a thread."""
    if hasattr(source, "__aiter__"):
        iterator = source.__aiter__()  # type: ignore[union-attr]
        try:
            async for item in iterator:
                yield item
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
        return

    iterator: Iterator[Any] = iter(source)  # type: ignore[arg-type]
    try:
        while True:
            item = await asyncio.to_thread(next, iterator, _END)
            if item is _END:
                return
            yield item
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            await asyncio.to_thread(close)
