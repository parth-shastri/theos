"""Harness checkpoints and application approval policy."""

import json
import time
from time import monotonic

from harness import (
    Hooks,
    UserMessage,
    message_to_dict,
)
from theos.runtime.models import session_options
from theos.storage.messages import stamp_message

from .approvals import check_approval
from .context import ResearchStopped, options
from .text import reply_text


def build_hooks(runtime, session, *, limits=None, deadline=None):
    """Save model and tool checkpoints at the harness execution boundaries."""
    owner = session["owner"]
    session_id = session["id"]
    started = None
    created_at = None

    async def before_model(request, ctx):
        nonlocal started, created_at
        # Add sandbox images once, after the file catalog checks their owner.
        for file_id in ctx.state.pop("view_images", []):
            image = UserMessage("Image from the sandbox:", [runtime.files.image(owner, file_id)])
            stamp_message(image)
            ctx.history.append(image)
            request.messages.append(image)
        if deadline is not None and monotonic() >= deadline:
            raise ResearchStopped("The research reached its time limit.")
        request.options.update(
            options(runtime, session, limits)
            if limits
            else session_options(runtime.settings, session)
        )
        started = time.monotonic()
        created_at = time.time()
        return request

    async def after_model(message, ctx):
        if message.text is not None:
            message.text = reply_text(message.text)
        if message.reasoning is not None:
            message.reasoning = reply_text(message.reasoning)
        stamp_message(
            message,
            created_at=created_at,
            duration_ms=(time.monotonic() - started) * 1000 if started is not None else None,
        )
        # Save the tool call and usage together before the harness executes the call.
        with runtime.db.transaction():
            runtime.db.save_history(
                owner, session_id, [*ctx.history, message], ctx.memory.to_dict()
            )
            runtime.record_usage(session, message.usage)
        return message

    async def before_tool(tool, args, ctx):
        if deadline is not None and monotonic() >= deadline:
            raise ResearchStopped("The research reached its time limit.")
        decision = await check_approval(runtime, session, tool, args, ctx)
        if decision.kind != "allow":
            with runtime.tracing.span(
                f"execute_tool {tool.name}",
                {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": tool.name,
                    "theos.tool.status": "waiting_for_approval"
                    if decision.kind == "ask"
                    else "denied",
                },
            ):
                pass
        return decision

    async def after_tool(result, ctx):
        if result.name == "sandbox_view_image" and result.status == "completed":
            value = json.loads(result.content)
            ctx.state.setdefault("view_images", []).append(value["file_id"])
        # This hook runs before the harness resumes the model, so results survive a process exit.
        runtime.db.execute(
            "INSERT INTO tool_runs VALUES (?,?,?,?,?) ON CONFLICT(session,call_id) DO UPDATE SET "
            "status=excluded.status,result=excluded.result",
            (
                session_id,
                result.call_id,
                result.name,
                result.status,
                json.dumps(message_to_dict(result)),
            ),
        )
        return result

    return Hooks(
        before_model=before_model,
        after_model=after_model,
        before_tool=before_tool,
        after_tool=after_tool,
    )
