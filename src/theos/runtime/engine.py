"""Persistent harness turns, approval checks, and bounded conversation concurrency."""

import asyncio
import json
import logging
import time
from contextlib import AsyncExitStack, aclosing, asynccontextmanager
from datetime import UTC, datetime
from functools import partial

import httpx

from harness import (
    Agent,
    ContextCompaction,
    HarnessError,
    ToolResultMessage,
    UserMessage,
)
from harness.compaction import ContextMemory
from harness.prompting import validate_prompts
from theos.operations.tracing import Tracing
from theos.prompts import render
from theos.runtime.models import model_client
from theos.services.files.catalog import Files
from theos.services.memory.client import MemoryClient
from theos.services.preferences.tools import preferences
from theos.storage.messages import stamp_message, update_display_metadata

from . import approvals, checkpoints, context, hooks, recovery, speech, titles, tools
from .budgets import TurnBudget
from .errors import CheckedModel
from .events import publish_event
from .fallback import FallbackModel
from .model_catalog import fallback_reasoning, wire_model
from .reviews import approval_review, tool_label
from .text import reply_text
from .turn import Turn
from .usage import record_usage

logger = logging.getLogger("theos")


class Runtime:
    """Own clients, active tasks, and per-conversation locks."""

    def __init__(self, settings, db, http=None, models=model_client, *, enforce_budgets=False):
        # Runtime is the application coordinator: it owns shared clients and service objects,
        # while harness.Agent owns only the generic model/tool loop for one run.
        validate_prompts("harness")
        validate_prompts("theos")
        self.settings = settings
        self.enforce_budgets = enforce_budgets
        self.db = db
        self.http = http or httpx.AsyncClient(timeout=30, follow_redirects=False)
        self.tracing = Tracing(settings.tracing)

        # Wrap the selected provider client so model calls become child trace spans.
        # The context manager also controls the SDK client's lifetime for one turn.
        @asynccontextmanager
        async def traced_models(settings, model_id, reasoning):
            fallback_model = settings.fallback_model
            if fallback_model is None:
                fallback_model = {
                    "openai": "gpt-5.6-luna",
                    "openrouter": "glm-5.3",
                }.get(settings.provider, "")
            fallback_model = fallback_model.strip()
            if fallback_model and wire_model(settings.provider, fallback_model) != wire_model(
                settings.provider, model_id
            ):
                # Keep the configured model primary. FallbackModel retries only the
                # provider failures its own policy recognizes, then traces that attempt too.
                from .errors import CheckedModel

                @asynccontextmanager
                async def fallback_connection():
                    fallback_effort = fallback_reasoning(
                        settings.provider, fallback_model, reasoning
                    )
                    async with models(settings, fallback_model, fallback_effort) as fallback:
                        yield CheckedModel(
                            self.tracing.model(
                                fallback,
                                reasoning=fallback_effort,
                                attributes={
                                    "theos.provider.fallback.attempt": True,
                                    "theos.provider.fallback.primary_model": model_id,
                                },
                            ),
                            settings.provider,
                        )

                async with models(settings, model_id, reasoning) as primary:
                    yield FallbackModel(
                        CheckedModel(
                            self.tracing.model(
                                primary,
                                reasoning=reasoning,
                                attributes={
                                    "theos.provider.fallback.available_model": fallback_model
                                },
                            ),
                            settings.provider,
                        ),
                        fallback_connection,
                        fallback_model,
                        settings.provider,
                        self.tracing,
                    )
                return
            # No fallback is configured (or it is the same model): use one traced client.
            async with models(settings, model_id, reasoning) as model:
                yield self.tracing.model(model, reasoning=reasoning)

        self.models = traced_models
        # Construct shared service clients once. Individual turns receive tools that use
        # these clients; they do not create new HTTP pools or database connections per call.
        self.memory = MemoryClient(settings.memory, self.http)
        from theos.services.memory.automation import MemoryAutomation

        self.memory_automation = MemoryAutomation(self)
        self.files = Files(settings, db, self.http, speech_renderer=partial(speech.prepare, self))
        from theos.services.files.checkpoints import Checkpoints
        from theos.services.sandbox.workspace import Workspaces

        self.checkpoints = Checkpoints(self.files, self.tracing)
        self.checkpoints.start()
        self.workspaces = Workspaces(self)
        from theos.services.research.store import Research

        self.research = Research(db)
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_turns)
        self.locks: dict[str, asyncio.Lock] = {}
        self.active: dict[str, Turn] = {}
        self.closed = False
        from theos.services.calendar.client import Calendar
        from theos.services.github import create_account as create_github_account
        from theos.services.gmail.client import Gmail
        from theos.services.google.oauth import OAuth
        from theos.services.health.client import Health
        from theos.services.sandbox.client import Sandboxes
        from theos.services.slack import create_account as create_slack_account
        from theos.services.zepto.auth import Zepto

        self.oauth = OAuth(settings, db, self.http)
        self.gmail = Gmail(self.oauth, self.http, self.files)
        self.calendar = Calendar(self.oauth, self.http, settings, db)
        self.health = Health(self.oauth, settings, db, self.http)
        self.sandboxes = Sandboxes(settings, db, self.files)
        from theos.services.sandbox.browser import Browsers

        self.browsers = Browsers(self)
        self.sandboxes.browsers = self.browsers
        self.zepto = Zepto(settings, db, self.http)
        self.slack = create_slack_account(settings, db, self.http)
        self.github = create_github_account(settings, db, self.http)
        from theos.services.github.notifications import GitHubNotifications

        self.github_events = GitHubNotifications(settings, db, self.http, self.github)

    def lock(self, session_id):
        """Return the lock that serializes one conversation."""
        return self.locks.setdefault(session_id, asyncio.Lock())

    def session(self, owner, session_id):
        """Read a conversation only when it belongs to the owner."""
        return self.db.session(owner, session_id)

    def pending(self, owner, session_id):
        """List current approvals after expiring old decisions."""
        self.session(owner, session_id)
        self.db.execute(
            "UPDATE approvals SET status='expired' WHERE session=? AND status='pending' AND expires<=?",
            (session_id, time.time()),
        )
        rows = self.db.rows(
            "SELECT id,call_id,tool,arguments,preview,expires FROM approvals WHERE session=? AND status='pending' ORDER BY created",
            (session_id,),
        )
        for row in rows:
            if not approvals.requires_approval(row["tool"]):
                self.db.execute(
                    "UPDATE approvals SET status='not_required' WHERE id=?", (row["id"],)
                )
        rows = [row for row in rows if approvals.requires_approval(row["tool"])]
        return [
            {
                **row,
                "label": tool_label(row["tool"]),
                "review": approval_review(row["tool"], json.loads(row["preview"])),
            }
            for row in rows
        ]

    def start(
        self,
        owner,
        session_id,
        text=None,
        file_ids=(),
        approval=None,
        *,
        scheduled=False,
        raw_events=False,
        mode="normal",
        browser_ui=False,
        tools_disabled=False,
        text_recovery=False,
        display_text=None,
    ):
        """Reserve one turn before a response stream starts."""
        # First establish that this conversation belongs to the caller. Do this before
        # reading attachment IDs or changing the saved approval state.
        session = self.session(owner, session_id)
        if self.closed:
            raise RuntimeError("The application is shutting down.")
        if session_id in self.active:
            raise ValueError("This conversation already has a running turn.")
        if text is not None and self.pending(owner, session_id):
            raise ValueError("Resolve the pending approval before you send another message.")
        # Convert text and owned file IDs into the harness' UserMessage shape once, at the
        # application boundary. The harness never needs to know Telegram's file format.
        message = (
            self.input_message(owner, text, file_ids) if text is not None or file_ids else None
        )
        if display_text is not None:
            if message is None or not isinstance(display_text, str) or len(display_text) > 500:
                raise ValueError("The interface action display text is invalid.")
            update_display_metadata(message, {"user_text": display_text})
        if approval:
            # The transport sends an approval ID and yes/no choice, not tool arguments.
            # Load the saved approval so a client cannot edit the action while approving it.
            approval_id, approved = approval
            row = self.db.one(
                "SELECT * FROM approvals WHERE id=? AND session=?", (approval_id, session_id)
            )
            if not row or row["status"] != "pending" or row["expires"] <= time.time():
                raise ValueError("This approval is absent, expired, or already used.")
            self.db.execute(
                "UPDATE approvals SET status=? WHERE id=?",
                ("approved" if approved else "denied", approval_id),
            )
        from .research_mode import explicit_request

        research_task = explicit_request(text, mode) if text is not None else None
        openui_version = None
        if browser_ui:
            from .openui import library_version

            openui_version = library_version()
        # Turn holds only live delivery state; SQLite remains the source of durable history.
        turn = Turn(
            owner,
            session_id,
            raw_events=raw_events,
            include_delegate_tool_progress=session["channel"].startswith("telegram"),
            browser_ui=browser_ui,
            tools_disabled=tools_disabled,
            text_recovery=text_recovery,
            library_version=openui_version,
            research_task=research_task,
        )
        # Reserve synchronously. Two incoming requests must not start the same conversation
        # between this check and the background task acquiring its async lock.
        self.active[session_id] = turn
        turn.task = asyncio.create_task(
            self.run(
                turn,
                session,
                message,
                scheduled=scheduled,
            )
        )
        return turn

    def input_message(self, owner, text, file_ids=()):
        """Build a message after checking each attachment's owner."""
        # Check ownership before supplying image pixels or automatic workspace paths.
        # Input metadata lets the pre-model hook stage each selected file once.
        images = []
        text = text or ""
        for file_id in file_ids:
            row = self.files.get(owner, file_id)
            if row["media_type"].startswith("image/"):
                images.append(self.files.image(owner, file_id))
            if self.settings.sandbox.enabled:
                text += f"\nAttached file: {row['name']} at {self.workspaces.input_path(row)}"
            else:
                text += f"\nAttached file: {row['name']} (file ID {file_id})"
        message = stamp_message(UserMessage(text, images))
        if file_ids and self.settings.sandbox.enabled:
            update_display_metadata(message, {"workspace_files": list(file_ids)})
        return message

    def steer(self, owner, session_id, text, file_ids=()):
        """Queue owned input for the active turn's next model boundary."""
        self.session(owner, session_id)
        turn = self.active.get(session_id)
        if turn is None or self.closed:
            raise ValueError("This conversation has no running turn.")
        if self.pending(owner, session_id):
            raise ValueError("Resolve the pending approval before you send steering.")
        turn.inbox.steer(self.input_message(owner, text, file_ids))

    async def reset(self, owner, session_id):
        """Clear conversation state while keeping personal records and files."""
        self.session(owner, session_id)
        if session_id in self.active:
            raise ValueError("Wait for the running turn before you reset this conversation.")
        async with self.lock(session_id):
            with self.db.transaction():
                self.db.execute("DELETE FROM approvals WHERE session=?", (session_id,))
                self.db.execute("DELETE FROM tool_runs WHERE session=?", (session_id,))
                self.db.save_history(owner, session_id, [], {}, "idle")
                self.db.execute(
                    "UPDATE sessions SET title='New conversation',title_attempts=0 WHERE id=? AND owner=? AND title_auto=1",
                    (session_id, owner),
                )
                self.db.execute(
                    "UPDATE scheduled_runs SET status='abandoned', finished=? "
                    "WHERE session=? AND status IN ('waiting_for_approval','budget_exhausted')",
                    (time.time(), session_id),
                )

    async def tools(self, session):
        """Build tools that this conversation can access."""
        # A remotely restored conversation may need operator review before it can make
        # further external changes, so expose no tools until that review is complete.
        if self.db.one(
            "SELECT id FROM records WHERE owner=? AND kind='remote_recovery_review' AND id=?",
            (session["owner"], session["id"]),
        ):
            return []
        return await tools.build_tools(self, session)

    def journal_tool(self, original, session):
        """Record a tool attempt before its external effects can start."""
        return self.tracing.tool(checkpoints.journal_tool(self, original, session))

    async def approval_preview(self, session, name, arguments):
        """Read the exact action contents that the user must approve."""
        return await approvals.approval_preview(self, session, name, arguments)

    def record_usage(self, session, usage, *, model_id=None):
        """Store token counters and configured cost estimates without prompt content."""
        return record_usage(self, session, usage, model_id=model_id)

    def hooks(self, session):
        """Connect durable checkpoints and approval policy to the harness."""
        return hooks.build_hooks(self, session)

    def recover_history(self, owner, session_id):
        """Restore saved results and mark interrupted actions as uncertain."""
        return checkpoints.recover_history(self, owner, session_id)

    async def run(self, turn, session, message, *, scheduled=False):
        """Trace one turn independently of the transport and other active turns."""
        with self.tracing.turn(session, scheduled, self.settings.name, started_at=turn.started_at):
            await self._run(turn, session, message, scheduled=scheduled)

    async def _run(self, turn, session, message, *, scheduled=False):
        # Recovery retains the same conversation lock and application concurrency slot.
        try:
            from contextlib import AsyncExitStack

            self.checkpoints.tracing = self.tracing
            self.checkpoints.start()
            async with AsyncExitStack() as stack:
                with self.tracing.span("runtime wait"):
                    # Serialize turns in one conversation and cap total concurrent work
                    # across different conversations before touching history.
                    await stack.enter_async_context(self.lock(turn.session_id))
                    await stack.enter_async_context(self.semaphore)
                await self._run_reserved(turn, session, message, scheduled=scheduled)
        except asyncio.CancelledError:
            if self.active.pop(turn.session_id, None) is not None:
                self.tracing.finish_turn("interrupted")
                turn.emit({"type": "done", "status": "interrupted", "stats": turn.stats()})
            raise

    async def _run_reserved(self, turn, session, message, *, scheduled=False):
        """Run one reserved turn and save its final state."""
        status = "failed"
        started = time.monotonic()
        # Keep configured deadlines for bounded callers. Theos permits long tasks.
        deadline = started + self.settings.turn_timeout if self.enforce_budgets else None
        turn.research_deadline = deadline
        allowances = TurnBudget(self.settings, enforce=self.enforce_budgets)
        turn.budgets = allowances
        budget = allowances.research
        instructions = ""
        reason = None
        failure = None
        # 1. Restore the transcript and prior tool results. In particular, do not repeat a
        # tool call whose outcome became uncertain when a previous process stopped.
        with self.tracing.span("runtime restore"):
            history = self.recover_history(turn.owner, turn.session_id)
        history_offset = len(history)
        memory = ContextMemory.from_dict(json.loads(session["memory"]))
        source_text = message.content if message and not scheduled else ""
        try:
            try:
                # 2. Accept input only after acquiring the locks. This keeps the current
                # message ordered after the previous turn and avoids overlapping history edits.
                if message:
                    if not history and session["title_auto"]:
                        title = (
                            reply_text(" ".join(message.content.split()))[:80] or "Attached files"
                        )
                        self.db.execute(
                            "UPDATE sessions SET title=? WHERE id=?", (title, turn.session_id)
                        )
                    history.append(message)
                if turn.research_task:
                    turn.research_id = self.research.create(
                        turn.owner, turn.session_id, "Lead researcher", turn.research_task
                    )
                # 3. Save the accepted message before the provider can request a tool. If the
                # process exits mid-turn, the user's input is still part of the conversation.
                self.db.save_history(turn.owner, turn.session_id, history, status="running")
                # Deadlines stop new work through hooks, never a running generation.
                async with AsyncExitStack() as model_stack:
                    model = await model_stack.enter_async_context(
                        self.models(self.settings, session["model"], session["reasoning"])
                    )
                    summary_model = None
                    if (
                        self.settings.compaction_model
                        and self.settings.compaction_model != session["model"]
                    ):
                        summary_model = await model_stack.enter_async_context(
                            self.models(
                                self.settings,
                                self.settings.compaction_model,
                                session["reasoning"],
                            )
                        )
                    model = CheckedModel(model, self.settings.provider)
                    if summary_model is not None:
                        summary_model = CheckedModel(summary_model, self.settings.provider)
                    # Provider limits determine how much history and output can fit in a request.
                    with self.tracing.span("runtime model capacity"):
                        limits = await context.capacity(self, session)
                        summary_session = None
                        summary_limits = limits
                        if summary_model is not None:
                            summary_session = {
                                **session,
                                "model": self.settings.compaction_model,
                                "generation": "{}",
                            }
                            summary_limits = await context.capacity(self, summary_session)
                    # The registry is owner- and channel-specific. It is what lets the same
                    # generic harness loop expose different services to different users.
                    with self.tracing.span("runtime tool registry"):
                        tools = [] if turn.tools_disabled else await self.tools(session)
                    user_preferences = preferences(self.db, turn.owner, self.settings.timezone)
                    query = (
                        message.content
                        if message
                        else next(
                            (m.content for m in reversed(history) if isinstance(m, UserMessage)),
                            "",
                        )
                    )
                    with self.tracing.span("runtime memory retrieval"):
                        retrieved = await self.memory_automation.retrieve(session, query)
                    # These are Theos' application rules and user context. The harness adds
                    # its own generic instructions for safe tool execution and call limits.
                    prompt_time = datetime.now(UTC).isoformat()
                    recovery_review = bool(
                        self.db.one(
                            "SELECT id FROM records WHERE owner=? AND kind='remote_recovery_review' AND id=?",
                            (turn.owner, turn.session_id),
                        )
                    )
                    from theos.services.skills.context import skill_context

                    skill_instructions, loaded = skill_context(
                        self.settings,
                        "\n".join(m.content for m in history if isinstance(m, UserMessage))[
                            -12000:
                        ],
                    )
                    turn.loaded_skills.update(loaded)
                    # Resolve capabilities in Python. Templates receive only plain turn data.
                    instructions = render(
                        "chat/system.md",
                        agent_name=self.settings.name,
                        current_utc=prompt_time,
                        preferences_json=json.dumps(user_preferences),
                        recovery_review=recovery_review,
                        sandbox_enabled=self.settings.sandbox.enabled,
                        skill_instructions=skill_instructions,
                        research_enabled=bool(turn.research_id),
                        allow_delegation=True,
                        retrieved_memory=retrieved,
                        telegram=session["channel"].startswith("telegram"),
                    )
                    if turn.browser_ui or turn.text_recovery:
                        from theos.runtime.openui import system_prompt

                        policy = render(
                            "chat/openui-policy.md"
                            if turn.browser_ui
                            else "chat/openui-recovery.md",
                            timezone=user_preferences.get("timezone", self.settings.timezone),
                        )
                        instructions = "\n\n".join(
                            part.strip()
                            for part in (
                                instructions,
                                policy,
                                system_prompt() if turn.browser_ui else "",
                            )
                            if part.strip()
                        )
                    # This is the boundary between Theos and the harness: application
                    # objects are passed in; the harness does not import Theos services.
                    agent = Agent(
                        model,
                        tools,
                        instructions,
                        hooks.build_hooks(self, session, limits=limits, deadline=deadline),
                        context_window=limits.context,
                        compaction=context.compaction(
                            self,
                            session,
                            limits,
                            turn.research_id,
                            summary_model=summary_model,
                            summary_session=summary_session,
                            summary_limits=summary_limits,
                        ),
                    )
                    # 4. Run the harness. It handles model/tool/model cycles; the hooks
                    # supplied above persist each important boundary in the application DB.
                    events = agent.run_stream(
                        history,
                        budget=budget,
                        compaction_budget=allowances.compaction,
                        memory=memory,
                        inbox=turn.inbox,
                    )
                    async with aclosing(events):
                        async for event in events:
                            if isinstance(event, ContextCompaction):
                                if event.status == "progress" and event.model_calls:
                                    self.record_usage(session, event.usage)
                                elif event.status == "completed":
                                    await self.checkpoints.save(
                                        turn.owner, turn.session_id, history, memory, "compaction"
                                    )
                                    # Commit the summary boundary before the next provider call.
                                    self.db.save_history(
                                        turn.owner, turn.session_id, history, memory.to_dict()
                                    )
                            # Persist important data in hooks first; this event path is only
                            # for progress/UI delivery and may be consumed after a delay.
                            status = publish_event(self, turn, event, status)
                    if turn.provider_failure:
                        raise turn.provider_failure
                    if status == "budget_exhausted":
                        reason = "budget_limit"
                    elif status == "completed" and history[-1].stop_reason == "length":
                        reason = "output_limit"
                    elif status == "completed" and any(
                        result["status"] != "completed"
                        for group in turn.delegate_results.values()
                        for result in group.values()
                    ):
                        reason = "delegate_partial"
                    if (
                        reason is None
                        and status == "completed"
                        and message
                        and not scheduled
                        and time.monotonic() - started < self.settings.turn_timeout - 9
                    ):
                        await titles.update_title(
                            self, turn, session, model, history, budget=budget
                        )
            except Exception as error:
                # Preserve the failure and classify it. Recovery may ask the model for a
                # bounded final response, but it must not replay already-run tools.
                failure = error
                reason = recovery.failure_reason(error)
                logger.warning(
                    "turn_incomplete",
                    extra={
                        "error_type": type(error).__name__,
                        "error_code": error.code.value if isinstance(error, HarnessError) else None,
                        "reason": reason,
                        "session_id": turn.session_id,
                    },
                )
            if reason:
                status = await recovery.finish(
                    self,
                    turn,
                    session,
                    history,
                    memory,
                    history_offset,
                    allowances.recovery,
                    instructions,
                    reason,
                    error=failure,
                )
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        finally:
            # 5. Save final history and memory before releasing the conversation lock. This
            # also runs after exceptions or cancellation, so restart recovery has a boundary.
            history.extend(turn.inbox.drain())
            self.db.save_history(turn.owner, turn.session_id, history, memory.to_dict(), status)
            await self.checkpoints.save(turn.owner, turn.session_id, history, memory, "turn_end")
            if turn.research_id:
                from harness import AssistantMessage

                self.research.checkpoint(
                    turn.owner, turn.session_id, turn.research_id, history, memory
                )
                last_answer = next(
                    (
                        m.text
                        for m in reversed(history[history_offset:])
                        if isinstance(m, AssistantMessage) and m.text and not m.tool_calls
                    ),
                    "",
                )
                self.research.finish(
                    turn.owner, turn.session_id, turn.research_id, status, last_answer, reason
                )
            allowances.final_compaction.release()
            if status == "completed" and source_text:
                try:
                    self.memory_automation.enqueue(session, source_text)
                except Exception:
                    logger.warning("memory_enqueue_failed")
            run_status = (
                "uncertain"
                if any(
                    isinstance(m, ToolResultMessage) and m.status == "unknown"
                    for m in history[history_offset:]
                )
                else status
            )
            self.tracing.finish_turn(run_status, allowances.attributes())
            updated_runs = self.db.execute(
                "UPDATE scheduled_runs SET status=?, finished=? WHERE session=? "
                "AND status IN ('running','waiting_for_approval','budget_exhausted') RETURNING task_id",
                (run_status, time.time(), turn.session_id),
            ).fetchall()
            if run_status in {"failed", "interrupted", "budget_exhausted", "uncertain", "partial"}:
                for run in updated_runs:
                    self.db.execute(
                        "UPDATE scheduled_tasks SET status='paused' "
                        "WHERE status IN ('pending','completed') AND id=?",
                        (run["task_id"],),
                    )
            self.active.pop(turn.session_id, None)
            turn.emit({"type": "done", "status": status, "stats": turn.stats()})

    async def close(self):
        """Stop new work, cancel active turns, and close owned clients."""
        self.closed = True
        tasks = [turn.task for turn in self.active.values() if turn.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.checkpoints.close()
        await self.zepto.close()
        await self.slack.close()
        await self.github.close()
        await self.browsers.close()
        await self.sandboxes.close()
        await self.http.aclose()
        await self.tracing.close()
