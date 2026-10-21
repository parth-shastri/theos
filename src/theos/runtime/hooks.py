"""Connect generic harness boundaries to Theos saves, approvals, and recovery data."""

import json
import time
from time import monotonic

from harness import (
    Hooks,
    UserMessage,
    message_to_dict,
)
from theos.runtime.models import session_options
from theos.storage.messages import stamp_message, update_display_metadata

from .approvals import check_approval
from .context import ResearchStopped, options
from .text import reply_text
from .usage import message_model


def build_hooks(runtime, session, *, limits=None, deadline=None):
    """Save model and tool checkpoints at the harness execution boundaries."""
    # Hooks are callbacks the harness runs around work. This keeps the generic loop free
    # of SQLite and Theos-specific rules while making those rules run at exact boundaries.
    owner = session["owner"]
    session_id = session["id"]
    started = None
    created_at = None

    async def before_model(request, ctx):
        nonlocal started, created_at
        turn = runtime.active.get(session_id)
        if turn and turn.provider_failure:
            raise turn.provider_failure
        # Add sandbox images once, after the file catalog checks their owner. The view_image
        # tool records IDs in run state; this hook turns those IDs into model image inputs.
        for file_id in ctx.state.pop("view_images", []):
            image = UserMessage("Image from your workspace:", [runtime.files.image(owner, file_id)])
            stamp_message(image)
            ctx.history.append(image)
            request.messages.append(image)
        if deadline is not None and monotonic() >= deadline:
            raise ResearchStopped("The research reached its time limit.")
        # Apply this conversation's model and generation settings at the last safe point
        # before sending a request, rather than storing provider options in the transcript.
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
        # A checkpoint before each call makes the exact prompt/history available for restart
        # recovery and diagnostics if the process stops while the provider is responding.
        await runtime.checkpoints.save(owner, session_id, ctx.history, ctx.memory, "before_model")
        started = time.monotonic()
        created_at = time.time()
        return request

    async def after_model(message, ctx):
        turn = runtime.active.get(session_id)
        # Clean generated punctuation and attach display-only timing metadata before saving.
        if message.text is not None:
            message.text = reply_text(message.text)
        if message.reasoning is not None:
            message.reasoning = reply_text(message.reasoning)
        stamp_message(
            message,
            created_at=created_at,
            duration_ms=(time.monotonic() - started) * 1000 if started is not None else None,
        )
        if turn.browser_ui and message.text:
            turn.prepare_output()
            if message.tool_calls:
                update_display_metadata(message, {"openui_hidden": True})
            else:
                update_display_metadata(
                    message,
                    {
                        "format": "openui-lang",
                        "library_version": turn.library_version,
                        "openui_message_id": turn.output_message_id,
                        "openui_state": {},
                    },
                )
        # Save the assistant message and usage together before the harness executes any
        # requested tool. A crash after this point can identify the action that was pending.
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
        # This is the last application gate before a tool's side effect. It can allow,
        # deny, or pause the call for an owner approval.
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
        if result.name == "view_image" and result.status == "completed":
            value = json.loads(result.content)
            ctx.state.setdefault("view_images", []).append(value["file_id"])
        # Save the exact result before the harness asks the model what to do next. After a
        # restart, recovery can pair this result with its call instead of running it again.
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
