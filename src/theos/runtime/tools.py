"""Register service tools allowed for each conversation."""

import asyncio
import logging
from contextlib import aclosing
from typing import Annotated

from pydantic import Field

from harness import (
    Agent,
    Hooks,
    RunContext,
    UserMessage,
    collect_run_stream,
    tool,
)
from theos.services.custom_tables.tools import custom_tools
from theos.services.errors import ServiceError
from theos.services.files.tools import file_tools
from theos.services.information import information_tools
from theos.services.memory.tools import memory_tools
from theos.services.personal import personal_tools
from theos.services.schedules.tools import task_tools
from theos.services.voice.tools import voice_tools
from theos.storage.account_access import account_access

from .models import session_options

logger = logging.getLogger("theos")


async def build_tools(runtime, session):
    """Register service tools and attach durable execution checkpoints."""
    owner = session["owner"]
    session_id = session["id"]
    tools = personal_tools(runtime.db, owner, session_id, runtime.settings.timezone)
    tools += custom_tools(runtime.db, owner, runtime.settings.data_dir / "tables")
    tools += information_tools(runtime.settings, runtime.http) + file_tools(runtime.files, owner)
    tools += voice_tools(runtime.files.voice, owner)
    tools += task_tools(runtime.db, owner, session_id, runtime.settings)
    if runtime.settings.memory.enabled:
        tools += memory_tools(runtime.memory, owner)
        if session["channel"] in {"browser", "telegram-private", "terminal"}:
            tools += runtime.memory_automation.tools(owner)
    if runtime.settings.sandbox.enabled:
        tools += runtime.sandboxes.tools(owner, session_id)
    # Personal accounts belong to the authenticated owner in a private conversation.
    if session["channel"] in {"browser", "telegram-private"} and account_access(
        runtime.settings, runtime.db, owner
    ):
        if runtime.settings.gmail.enabled:
            tools += runtime.gmail.tools(owner)
        if runtime.settings.health.enabled:
            tools += runtime.health.tools(owner)
        if runtime.settings.zepto_url and runtime.zepto.connected(owner):
            from theos.services.zepto.tools import zepto_tools

            try:
                tools += await zepto_tools(runtime.zepto, owner)
            except ServiceError:
                # Optional tool discovery must not prevent an ordinary conversation.
                logger.warning("integration_unavailable", extra={"error_type": "ZeptoUnavailable"})

    @tool
    async def delegate_tasks(
        tasks: Annotated[list[str], Field(min_length=1, max_length=3)], ctx: RunContext
    ):
        """Delegate up to three research tasks with read-only tools and a shared model-call budget."""

        async def research(question, index):
            with runtime.tracing.span(
                f"invoke_agent research {index}",
                {
                    "gen_ai.operation.name": "invoke_agent",
                    "gen_ai.agent.name": "research",
                    "theos.delegate.index": index,
                },
            ) as span:
                result = await run_research(question)
                if span is not None:
                    span.set_attribute("theos.agent.status", result["status"])
                    if result["status"] in {"failed", "interrupted"}:
                        runtime.tracing.failed(span, result["status"])
                return result

        async def run_research(question):
            if len(question) > 8000:
                raise ValueError("Each delegated task must contain at most 8000 characters.")
            async with runtime.models(
                runtime.settings, session["model"], session["reasoning"]
            ) as model:

                async def record_usage(message, child_ctx):
                    runtime.record_usage(session, message.usage)
                    return message

                async def before_model(request, child_ctx):
                    request.options.update(session_options(runtime.settings, session))
                    return request

                agent = Agent(
                    model,
                    [
                        runtime.tracing.tool(t)
                        for t in information_tools(runtime.settings, runtime.http)
                    ],
                    "Research the requested topic. Use read-only tools. Return findings and sources.",
                    hooks=Hooks(before_model=before_model, after_model=record_usage),
                    max_context_tokens=8000,
                )

                async def child_events():
                    async with aclosing(
                        agent.run_stream(
                            [UserMessage(question)],
                            budget=ctx.budget,
                        )
                    ) as stream:
                        async for event in stream:
                            if ctx.emit is not None:
                                ctx.emit(event)
                            yield event

                result = await collect_run_stream(child_events())
                return {
                    "status": result.status,
                    "answer": result.message.text if result.message else None,
                }

        # The parent shares its budget. A delegate cannot recursively start delegates or write account data.
        async with asyncio.timeout(90):
            return await asyncio.gather(
                *(research(question, index) for index, question in enumerate(tasks, start=1))
            )

    tools.append(delegate_tasks)
    return [runtime.journal_tool(t, session) for t in tools]
