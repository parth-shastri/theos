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
from .usage import message_model


def build_hooks(runtime, session, *, limits=None, deadline=None):
    """Save model and tool checkpoints at the harness execution boundaries."""
    owner = session["owner"]
    session_id = session["id"]
    started = None
    created_at = None

    async def before_model(request, ctx):
        nonlocal started, created_at
        turn = runtime.active.get(session_id)
        if turn and turn.provider_failure:
            raise turn.provider_failure
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
        turn = runtime.active.get(session_id)
        if turn and turn.research_id:
            runtime.research.attach(request, owner, session_id, turn.research_id)
            runtime.research.checkpoint(
                owner, session_id, turn.research_id, ctx.history, ctx.memory
            )
        await runtime.checkpoints.save(owner, session_id, ctx.history, ctx.memory, "before_model")
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
            runtime.record_usage(session, message.usage, model_id=message_model(message))
        await runtime.checkpoints.save(
            owner, session_id, [*ctx.history, message], ctx.memory, "after_model"
        )
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
        turn = runtime.active.get(session_id)
        if turn and turn.research_id:
            from theos.services.research.tools import capture_search

            result = capture_search(runtime, session, turn.research_id, result)
            runtime.research.checkpoint(
                owner, session_id, turn.research_id, [*ctx.history, result], ctx.memory
            )
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
        await runtime.checkpoints.save(
            owner, session_id, [*ctx.history, result], ctx.memory, "after_tool"
        )
        return result

    return Hooks(
        before_model=before_model,
        after_model=after_model,
        before_tool=before_tool,
        after_tool=after_tool,
    )
