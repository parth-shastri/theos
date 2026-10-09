"""Adapt durable Theos conversations to the generic terminal session interface."""

import asyncio
import base64
import json
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from harness import PendingApproval, ToolFinished, TurnFinished
from renderer.adapters import HarnessAdapter, events
from renderer.events import ApprovalRequested, Notice, RunFinished
from renderer.interactive import (
    InteractionReply,
    PromptInput,
    RuntimeInfo,
    SessionInfo,
    normalize_prompt,
)


def timestamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


class TerminalSession:
    """Bind local input to one terminal owner without bypassing runtime policy."""

    def __init__(self, runtime, owner):
        if not owner.startswith("terminal:") or not owner.removeprefix("terminal:").strip():
            raise ValueError("The terminal owner must use the terminal: prefix.")
        self.runtime = runtime
        self.db = runtime.db
        self.owner = owner

    def _session(self, session_id):
        row = self.runtime.session(self.owner, session_id)
        if row["channel"] != "terminal":
            raise LookupError("Terminal conversation not found.")
        return row

    def _state(self, session_id):
        row = self._session(session_id)
        try:
            return self.db.record(self.owner, "terminal_session", session_id)
        except LookupError:
            return {"cwd": row["address"], "archived": False, "timestamps": []}

    def _save_state(self, session_id, state):
        self.db.put_record(self.owner, "terminal_session", session_id, state)

    def create_session(self, session_id):
        if not session_id.strip() or len(session_id) > 200:
            raise ValueError("Use a session ID with 1 to 200 characters.")
        if self.db.one("SELECT id FROM sessions WHERE id=?", (session_id,)):
            raise ValueError("That session ID already exists. Use /resume to open it.")
        settings = self.runtime.settings
        self.db.create_session(
            self.owner,
            settings.model,
            settings.reasoning,
            channel="terminal",
            session_id=session_id,
        )
        self._save_state(
            session_id,
            {
                "cwd": str(Path.cwd().resolve()),
                "archived": False,
                "timestamps": [],
            },
        )

    def history(self, session_id):
        self._session(session_id)
        return self.db.load_history(self.owner, session_id)

    def sessions(self):
        return tuple(
            row["id"]
            for row in self.db.rows(
                "SELECT id FROM sessions WHERE owner=? AND channel='terminal' ORDER BY updated DESC",
                (self.owner,),
            )
        )

    def session_title(self, session_id):
        return self._session(session_id)["title"]

    def session_details(self):
        return tuple(
            SessionInfo(
                row["id"],
                row["title"],
                timestamp(row["created"]),
                timestamp(row["updated"]),
                self._state(row["id"]).get("cwd"),
                bool(self._state(row["id"]).get("archived")),
            )
            for row in self.db.rows(
                "SELECT * FROM sessions WHERE owner=? AND channel='terminal' ORDER BY updated DESC",
                (self.owner,),
            )
        )

    def history_timestamps(self, session_id):
        row = self._session(session_id)
        state = self._state(session_id)
        times = state.setdefault("timestamps", [])
        count = len(self.history(session_id))
        times = times[:count] + [timestamp(row["updated"])] * max(0, count - len(times))
        state["timestamps"] = times
        self._save_state(session_id, state)
        return tuple(times)

    def rename_session(self, session_id, title):
        self._session(session_id)
        title = title.strip()
        if not title or len(title) > 100:
            raise ValueError("Use a title with 1 to 100 characters.")
        if session_id in self.runtime.active:
            raise ValueError("Wait for the running turn before you rename this conversation.")
        self.db.execute(
            "UPDATE sessions SET title=?,title_auto=0,updated=? WHERE id=? AND owner=?",
            (title, time.time(), session_id, self.owner),
        )

    def archive_session(self, session_id, archived):
        state = self._state(session_id)
        state["archived"] = archived
        self._save_state(session_id, state)

    def pending_interactions(self, session_id):
        self._session(session_id)
        return tuple(
            ApprovalRequested(
                row["id"],
                row["tool"],
                json.loads(row["arguments"]),
                "Review this saved action.\n" + json.dumps(json.loads(row["preview"]), indent=2),
            )
            for row in self.runtime.pending(self.owner, session_id)
        )

    def respond(self, replies: Sequence[InteractionReply], *, session_id):
        self._session(session_id)
        if session_id in self.runtime.active:
            raise ValueError("Wait for the running turn before you answer approvals.")
        pending = {item.call_id for item in self.pending_interactions(session_id)}
        ids = [reply.request_id for reply in replies]
        # Validate the whole batch before saving any decision or resuming execution.
        if len(set(ids)) != len(ids) or any(
            reply.kind != "approval"
            or not isinstance(reply.value, bool)
            or reply.request_id not in pending
            for reply in replies
        ):
            raise ValueError("This approval is absent, expired, or already used.")
        with self.db.transaction():
            for reply in replies:
                self.db.execute(
                    "UPDATE approvals SET status=? WHERE id=? AND session=? AND status='pending'",
                    ("approved" if reply.value else "denied", reply.request_id, session_id),
                )

    def _attachments(self, prompt):
        if len(prompt.text) > 32000 or len(prompt.images) > 10:
            raise ValueError("Use at most 32000 text characters and 10 images per message.")
        file_ids = []
        for image in prompt.images:
            if not image.url.startswith("data:image/"):
                raise ValueError("Attach a local image or a clipboard image.")
            header, _, encoded = image.url.partition(",")
            row = self.runtime.files.save(
                self.owner,
                image.filename or "image",
                header.removeprefix("data:").removesuffix(";base64"),
                base64.b64decode(encoded, validate=True),
            )
            file_ids.append(row["id"])
        return file_ids

    def steer(self, prompt: PromptInput | str, *, session_id):
        self._session(session_id)
        payload = normalize_prompt(prompt)
        if session_id not in self.runtime.active:
            raise ValueError("This conversation has no running turn.")
        self.runtime.steer(self.owner, session_id, payload.text, self._attachments(payload))

    async def stream(self, prompt: PromptInput | str | None, *, session_id):
        self._session(session_id)
        pending = self.pending_interactions(session_id)
        if pending:
            if prompt is not None:
                raise ValueError("Resolve the pending approval before you send another message.")
            for request in pending:
                yield request
            yield RunFinished("waiting_for_approval", pending_count=len(pending))
            return
        payload = normalize_prompt(prompt) if prompt is not None else None
        if payload is not None and not payload.text.strip() and not payload.images:
            raise ValueError("Enter a message or attach a file.")
        self.history_timestamps(session_id)
        turn = self.runtime.start(
            self.owner,
            session_id,
            payload.text if payload else None,
            self._attachments(payload) if payload else (),
            raw_events=True,
        )
        adapter = HarnessAdapter()
        try:
            # Forward harness details. Finish only after the runtime saves its durable state.
            async for item in turn.events():
                if item["type"] == "harness":
                    event = item["event"]
                    if isinstance(event, TurnFinished) and event.parent_call_id is None:
                        continue
                    if isinstance(event, ToolFinished) and isinstance(
                        event.result, PendingApproval
                    ):
                        continue
                    for normalized in events(adapter(event)):
                        yield normalized
                elif item["type"] == "error":
                    yield Notice(item["message"], "error")
                elif item["type"] == "file":
                    row = self.runtime.files.get(self.owner, item["file_id"])
                    yield Notice(f"File: {row['name']}\n{row['path']}")
                elif item["type"] == "done":
                    pending = self.pending_interactions(session_id)
                    for request in pending:
                        yield request
                    yield RunFinished(item["status"], pending_count=len(pending))
        finally:
            # Closing the UI must cancel model work before its database closes.
            if not turn.task.done():
                turn.task.cancel()
            await asyncio.gather(turn.task, return_exceptions=True)
            self.history_timestamps(session_id)

    async def runtime_info(self, session_id):
        row = self._session(session_id)
        provider = self.runtime.settings.provider
        return RuntimeInfo(
            model=row["model"],
            provider=provider,
            api={"openai": "responses", "openrouter": "chat_completions"}.get(provider),
            tool_names=tuple(tool.name for tool in await self.runtime.tools(row)),
            permission_policy="Theos saved approvals. Allow once or deny. Decisions expire after 15 minutes.",
            storage=str(self.db.path),
        )

    def notifications(self):
        rows = self.db.rows(
            "SELECT n.* FROM notifications n JOIN sessions s ON s.id=n.session "
            "WHERE n.owner=? AND s.channel='terminal' AND n.delivered=0 ORDER BY n.created LIMIT 50",
            (self.owner,),
        )
        for row in rows:
            self.db.execute("UPDATE notifications SET delivered=1 WHERE id=?", (row["id"],))
        return rows
