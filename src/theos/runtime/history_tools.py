"""Read saved evidence without returning an unbounded connector payload."""

import json
from typing import Annotated, Literal

from pydantic import Field

from harness import AssistantMessage, RunContext, ToolResultMessage, tool

from .history_content import evidence_text


def history_tools():
    """Scope every read to the current agent's transcript, supplied by the harness."""

    def content(message, *, search=False):
        if isinstance(message, AssistantMessage):
            return json.dumps(
                {
                    "text": message.text,
                    "calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments}
                        for call in message.tool_calls
                        if not search or call.name not in {"history_read", "history_search"}
                    ],
                },
                ensure_ascii=False,
            )
        return message.content

    @tool
    async def history_read(
        ctx: RunContext,
        message_index: Annotated[int | None, Field(ge=0)] = None,
        call_id: str | None = None,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=12000)] = 4000,
        view: Literal["raw", "text"] = "raw",
    ):
        """Read a page of original evidence omitted during compaction. Use a saved message index or tool call_id. Continue with next_offset until it is null. Check complete evidence before calculating totals. For MIME email payloads, view=text decodes plain text and HTML bodies, with source references. Attachments require separate access. Offsets refer to the selected view."""
        index = message_index
        if call_id is not None:
            index = next(
                (
                    i
                    for i, m in enumerate(ctx.history)
                    if isinstance(m, ToolResultMessage) and m.call_id == call_id
                ),
                None,
            )
        if index is None or index >= len(ctx.history):
            raise ValueError("No matching message exists in this agent's history.")
        text = content(ctx.history[index])
        if view == "text":
            text = evidence_text(text)
        return {
            "message_index": index,
            "view": view,
            "offset": offset,
            "total_chars": len(text),
            "content": text[offset : offset + limit],
            "next_offset": offset + limit if offset + limit < len(text) else None,
        }

    @tool
    async def history_search(
        query: Annotated[str, Field(min_length=0, max_length=200)],
        ctx: RunContext,
        start_index: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
        view: Literal["raw", "text"] = "raw",
    ):
        """Find original evidence in this agent's saved history. An empty query lists saved source tool results with previews and pagination. Returns bounded snippets and message indices for history_read. Search matches are not complete evidence. Use view=text to search decoded text inside MIME email bodies."""
        matches = []
        needle = query.casefold()
        for i in range(start_index, len(ctx.history)):
            message = ctx.history[i]
            if isinstance(message, ToolResultMessage) and message.name in {
                "history_read",
                "history_search",
            }:
                continue
            if not query and not isinstance(message, ToolResultMessage):
                continue
            text = content(message, search=True)
            if view == "text":
                text = evidence_text(text)
            # Keep original offsets valid for Unicode case conversions.
            found = text.lower().find(query.lower()) if query.isascii() else -1
            if found < 0 and needle not in text.casefold():
                continue
            start = max(0, found - 120)
            matches.append(
                {
                    "message_index": i,
                    "snippet": text[start : start + 600],
                    "view": view,
                    "tool": message.name if isinstance(message, ToolResultMessage) else None,
                    "total_chars": len(text),
                }
            )
            if len(matches) >= limit:
                return {"matches": matches, "next_index": i + 1}
        return {"matches": matches, "next_index": None}

    return [history_read, history_search]
