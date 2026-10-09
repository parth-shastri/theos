"""Authenticated terminal access to the deployed user's shared workspace."""

import json
import time

from fastapi import Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from .wire import display_events, encode_event


class ClientSession(BaseModel):
    session_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$")


class ClientMetadata(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class ClientPrompt(BaseModel):
    text: str = Field(default="", max_length=32000)
    files: list[str] = Field(default_factory=list, max_length=10)


class ClientDecision(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    approved: StrictBool


class ClientDecisions(BaseModel):
    replies: list[ClientDecision] = Field(min_length=1, max_length=100)


def register_terminal(app, settings, current, identity, browser_session):
    """Use browser authentication without linking standalone terminal identities."""
    authenticated = Depends(identity)

    def state(db, owner, session_id):
        try:
            return db.record(owner, "terminal_client", session_id)
        except LookupError:
            return {"archived": False}

    def event_stream(runtime, turn):
        async def generate():
            async for event in display_events(runtime, turn):
                yield "data: " + json.dumps(encode_event(event)) + "\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "X-Theos-Terminal-Protocol": "1"},
        )

    @app.get("/api/terminal/info")
    async def info(owner=authenticated):
        return {
            "protocol": 1,
            "name": settings.name,
            "provider": settings.provider,
            "api": {"openai": "responses", "openrouter": "chat_completions"}.get(settings.provider),
            "turn_timeout": settings.turn_timeout,
            "max_upload_bytes": settings.max_upload_bytes,
        }

    @app.get("/api/terminal/sessions")
    async def sessions(request: Request, owner=authenticated):
        db = current(request).db
        rows = db.rows(
            "SELECT id,title,created,updated FROM sessions WHERE owner=? AND channel='browser' "
            "ORDER BY updated DESC",
            (owner,),
        )
        return [{**row, **state(db, owner, row["id"])} for row in rows]

    @app.post("/api/terminal/sessions")
    async def new_session(body: ClientSession, request: Request, owner=authenticated):
        db = current(request).db
        if db.one("SELECT id FROM sessions WHERE id=?", (body.session_id,)):
            raise ValueError("That session ID already exists. Use /resume to open it.")
        return db.create_session(
            owner, settings.model, settings.reasoning, session_id=body.session_id
        )

    @app.patch("/api/terminal/sessions/{session_id}")
    async def metadata(
        session_id: str, body: ClientMetadata, request: Request, owner=authenticated
    ):
        browser_session(request, owner, session_id)
        runtime = current(request)
        if body.title is not None:
            title = body.title.strip()
            if not title:
                raise ValueError("Enter a conversation title.")
            if session_id in runtime.active:
                raise ValueError("Wait for the running turn before you rename this conversation.")
            runtime.db.execute(
                "UPDATE sessions SET title=?,title_auto=0,updated=? WHERE id=? AND owner=?",
                (title, time.time(), session_id, owner),
            )
        if body.archived is not None:
            runtime.db.put_record(owner, "terminal_client", session_id, {"archived": body.archived})
        return {"saved": True}

    @app.post("/api/terminal/sessions/{session_id}/turn")
    async def turn(session_id: str, body: ClientPrompt, request: Request, owner=authenticated):
        browser_session(request, owner, session_id)
        if not body.text.strip() and not body.files:
            raise ValueError("Enter a message or attach a file.")
        runtime = current(request)
        return event_stream(
            runtime, runtime.start(owner, session_id, body.text, body.files, raw_events=True)
        )

    @app.post("/api/terminal/sessions/{session_id}/resume")
    async def resume(session_id: str, request: Request, owner=authenticated):
        browser_session(request, owner, session_id)
        runtime = current(request)
        return event_stream(runtime, runtime.start(owner, session_id, raw_events=True))

    @app.post("/api/terminal/sessions/{session_id}/steer")
    async def steer(session_id: str, body: ClientPrompt, request: Request, owner=authenticated):
        browser_session(request, owner, session_id)
        if not body.text.strip() and not body.files:
            raise ValueError("Enter a message or attach a file.")
        current(request).steer(owner, session_id, body.text, body.files)
        return {"saved": True}

    @app.post("/api/terminal/sessions/{session_id}/decisions")
    async def decisions(
        session_id: str, body: ClientDecisions, request: Request, owner=authenticated
    ):
        browser_session(request, owner, session_id)
        runtime = current(request)
        if session_id in runtime.active:
            raise ValueError("Wait for the running turn before you answer approvals.")
        pending = {row["id"] for row in runtime.pending(owner, session_id)}
        ids = [reply.request_id for reply in body.replies]
        if len(set(ids)) != len(ids) or any(request_id not in pending for request_id in ids):
            raise ValueError("This approval is absent, expired, or already used.")
        # Save the validated batch once. A separate resume starts execution.
        with runtime.db.transaction():
            for reply in body.replies:
                runtime.db.execute(
                    "UPDATE approvals SET status=? WHERE id=? AND session=? AND status='pending'",
                    ("approved" if reply.approved else "denied", reply.request_id, session_id),
                )
        return {"saved": True}
