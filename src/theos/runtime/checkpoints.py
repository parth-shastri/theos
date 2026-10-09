"""Durable tool attempts and conversation recovery."""

import json

import httpx

from harness import (
    Tool,
    ToolResultMessage,
    unanswered_calls,
)
from harness.events import _tool_scope
from harness.tools import OutcomeUnknown


def journal_tool(runtime, original, session):
    """Wrap one tool with a durable attempt record and uncertainty checks."""

    async def execute(args, ctx):
        call_id = _tool_scope.get()
        # 1. Reuse a saved result. Never repeat a call whose outcome is unknown.
        existing = runtime.db.one(
            "SELECT * FROM tool_runs WHERE session=? AND call_id=?", (session["id"], call_id)
        )
        if existing:
            if existing["status"] in {"running", "unknown"}:
                raise OutcomeUnknown(
                    "The earlier call may have completed. Check the external service before you repeat it."
                )
            if existing["result"] is not None:
                return json.loads(existing["result"])["content"]
        # 2. Commit before execution so a crash leaves evidence of the unfinished attempt.
        runtime.db.save_history(session["owner"], session["id"], ctx.history, ctx.memory.to_dict())
        runtime.db.execute(
            "INSERT OR REPLACE INTO tool_runs VALUES (?,?,?,?,NULL)",
            (session["id"], call_id, original.name, "running"),
        )
        try:
            # 3. Execute once. The after-tool hook saves the result before the next model call.
            return await original.execute(args, ctx)
        except (httpx.TimeoutException, httpx.TransportError, TimeoutError) as error:
            raise OutcomeUnknown(
                "The service connection ended. The action outcome is unknown."
            ) from error

    return Tool(original.name, original.description, original.input_model, execute, timeout_s=90)


def recover_history(runtime, owner, session_id):
    """Restore tool results without resending unfinished external actions."""
    history = runtime.db.load_history(owner, session_id)
    for call in unanswered_calls(history):
        row = runtime.db.one(
            "SELECT * FROM tool_runs WHERE session=? AND call_id=?", (session_id, call.id)
        )
        if row:
            if row["result"]:
                from harness import message_from_dict

                history.append(message_from_dict(json.loads(row["result"])))
            else:
                history.append(
                    ToolResultMessage(
                        call.id,
                        call.name,
                        "The earlier action outcome is unknown. Check before repeating it.",
                        "unknown",
                    )
                )
    return history
