"""FastAPI entry point for private chat, approvals, files, and operations."""

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from theos.operations.logging import configure_logging
from theos.runtime import Runtime
from theos.runtime.approvals import requires_approval
from theos.runtime.model_catalog import (
    GenerationConfig,
    generation_capabilities,
    model_choices,
    reasoning_choices,
    validate_generation,
)
from theos.runtime.scheduler import Scheduler
from theos.runtime.usage import usage_summary
from theos.services.errors import ServiceError
from theos.services.preferences.tools import preferences
from theos.settings import Settings
from theos.storage import browser_access
from theos.storage.database import Database
from theos.transports.browser.activity import activity_summary
from theos.transports.browser.auth import SESSION_COOKIE, register_auth, same_origin
from theos.transports.telegram.polling import Telegram


class NewSession(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=100)


class ChatInput(BaseModel):
    mode: Literal["normal", "deep_research"] = "normal"
    text: str = Field(default="", max_length=32000)
    files: list[str] = Field(default_factory=list, max_length=10)


class DecisionInput(BaseModel):
    approved: bool


class TranscriptionInput(BaseModel):
    file_id: str = Field(min_length=1, max_length=100)


class SpeechInput(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class SessionSettings(BaseModel):
    model: str
    reasoning: Literal["default", "none", "low", "medium", "high", "xhigh", "max"] = "default"
    generation: GenerationConfig | None = None


class BodyLimit:
    """Reject large request bodies before multipart parsing writes temporary files."""

    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > self.limit:
                raise HTTPException(413, "The request exceeds the upload limit.")
            return message

        await self.app(scope, bounded_receive, send)


def create_app(settings=None, runtime=None):
    """Build the application. Tests can supply a runtime with mocked providers."""
    settings = settings or Settings()
    owned = runtime is None

    @asynccontextmanager
    async def lifespan(app):
        handler = configure_logging(settings.data_dir / "logs")
        current = runtime or Runtime(settings, Database(settings.data_dir))
        app.state.runtime = current
        telegram = Telegram(current) if settings.telegram_token.get_secret_value() else None
        scheduler = Scheduler(current, telegram)
        app.state.scheduler = scheduler
        tasks = [asyncio.create_task(scheduler.run())]
        if telegram:
            tasks.append(asyncio.create_task(telegram.run()))
        logging.getLogger("theos").info("started")
        try:
            yield
        finally:
            # Stop workers before their shared database and HTTP client close.
            scheduler.stopping.set()
            if telegram:
                await telegram.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await scheduler.close()
            await current.close()
            if owned:
                current.db.close()
            handler.close()

    app = FastAPI(
        title=settings.name,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if runtime:
        app.state.runtime = runtime
    app.add_middleware(BodyLimit, limit=settings.max_upload_bytes + 65536)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    async def identity(request: Request):
        authorization = request.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        owner = None
        for user, secret in settings.users.items():
            if hmac.compare_digest(token.encode(), secret.get_secret_value().encode()):
                owner = user
        db = request.app.state.runtime.db
        if not owner and token:
            owner = browser_access.credential_owner(settings, db, token, "token")
        if not authorization and request.cookies.get(SESSION_COOKIE):
            owner = browser_access.credential_owner(
                settings, db, request.cookies[SESSION_COOKIE], "session"
            )
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                same_origin(request, settings)
        if not owner:
            raise HTTPException(401, "Supply your private browser token.")
        request.app.state.runtime.db.ensure_user(owner)
        return owner

    async def administrator(owner=Depends(identity)):
        if owner not in settings.admins:
            raise HTTPException(403, "Administrator access is required.")
        return owner

    def current(request):
        return request.app.state.runtime

    register_auth(app, settings, current)
    from .connections import register_connections

    register_connections(app, settings, current, identity)

    def browser_session(request, owner, session_id):
        row = current(request).session(owner, session_id)
        if row["channel"] != "browser":
            raise PermissionError("This conversation belongs to another transport.")
        return row

    from theos.transports.terminal.routes import register_terminal

    register_terminal(app, settings, current, identity, browser_session)

    @app.exception_handler(LookupError)
    async def not_found(request, error):
        return JSONResponse({"detail": "The requested record was not found."}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(PermissionError)
    async def forbidden(request, error):
        return JSONResponse({"detail": str(error)}, status_code=403)

    @app.exception_handler(ServiceError)
    async def service_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=502)

    @app.get("/live")
    async def live():
        return {"status": "alive"}

    @app.get("/ready")
    async def ready(request: Request):
        active = current(request)
        active.db.one("SELECT 1")
        configured = (
            settings.provider == "fake"
            or settings.provider == "llama"
            or bool(settings.api_key.get_secret_value())
        )
        if active.closed or not configured:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        return {"status": "ready"}

    @app.get("/health")
    async def health(request: Request):
        return await ready(request)

    @app.get("/api/me")
    async def me(request: Request, owner=Depends(identity)):
        return {
            "id": owner,
            "display_name": preferences(current(request).db, owner, settings.timezone).get(
                "display_name", ""
            ),
            "admin": owner in settings.admins,
            "models": model_choices(settings),
            "generation_capabilities": {
                model: generation_capabilities(settings.provider, model)
                for model in model_choices(settings)
            },
            "model": settings.model,
            "reasoning": settings.reasoning,
            "default_max_output_tokens": settings.max_output_tokens,
            "voice": {
                "transcription": bool(settings.transcription_url),
                "tts": bool(settings.kokoro_url),
                "max_upload_bytes": settings.max_upload_bytes,
            },
        }

    @app.get("/api/sessions")
    async def sessions(request: Request, owner=Depends(identity)):
        return current(request).db.rows(
            "SELECT id,title,model,reasoning,status,updated FROM sessions WHERE owner=? AND "
            "channel='browser' ORDER BY updated DESC LIMIT 100",
            (owner,),
        )

    @app.post("/api/sessions")
    async def new_session(body: NewSession, request: Request, owner=Depends(identity)):
        return current(request).db.create_session(
            owner, settings.model, settings.reasoning, title=body.title
        )

    @app.get("/api/sessions/{session_id}")
    async def session(session_id: str, request: Request, owner=Depends(identity)):
        row = browser_session(request, owner, session_id)
        row["history"] = json.loads(row["history"])
        row["generation"] = json.loads(row["generation"])
        row["approvals"] = current(request).pending(owner, session_id)
        row["usage"] = usage_summary(current(request).db, owner=owner, session=session_id)
        return row

    @app.get("/api/sessions/{session_id}/research")
    async def research_runs(session_id: str, request: Request, owner=Depends(identity)):
        browser_session(request, owner, session_id)
        return current(request).research.runs(owner, session_id)

    @app.get("/api/sessions/{session_id}/research/{run_id}")
    async def research_run(session_id: str, run_id: str, request: Request, owner=Depends(identity)):
        browser_session(request, owner, session_id)
        store = current(request).research
        row = store.get(owner, session_id, run_id)
        row["history"] = json.loads(row["history"])
        row["memory"] = json.loads(row["memory"])
        row["items"] = store.items(owner, session_id, run_id, family=True)
        row["checkpoints"] = current(request).db.rows(
            "SELECT id,history,memory,created FROM research_checkpoints WHERE run=? ORDER BY id",
            (run_id,),
        )
        return row

    @app.get("/api/usage")
    async def usage(request: Request, owner=Depends(identity)):
        return usage_summary(current(request).db, owner=owner)

    @app.get("/api/sessions/{session_id}/tools")
    async def tools(session_id: str, request: Request, owner=Depends(identity)):
        row = browser_session(request, owner, session_id)
        registered = await current(request).tools(row)
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.spec.parameters,
                "requires_approval": requires_approval(tool.name),
            }
            for tool in sorted(registered, key=lambda tool: tool.name)
        ]

    @app.patch("/api/sessions/{session_id}")
    async def update_session(
        session_id: str, body: SessionSettings, request: Request, owner=Depends(identity)
    ):
        session = browser_session(request, owner, session_id)
        active = current(request)
        if session_id in active.active or active.pending(owner, session_id):
            raise ValueError("Finish this turn and its approvals before you change settings.")
        if body.model not in model_choices(settings):
            raise ValueError("This model is not in the configured allowlist.")
        if body.reasoning not in reasoning_choices(settings.provider, body.model):
            raise ValueError("Choose a reasoning effort supported by this model.")
        # Switching models keeps only parameters supported by the new model.
        generation = (
            body.generation.model_dump(exclude_none=True)
            if body.generation is not None
            else {
                key: value
                for key, value in json.loads(session["generation"]).items()
                if key in generation_capabilities(settings.provider, body.model)["parameters"]
            }
        )
        if body.model != session["model"] and body.generation is None:
            limit = generation_capabilities(settings.provider, body.model)["max_output_tokens"]
            if generation.get("max_output_tokens", 0) > limit:
                generation["max_output_tokens"] = limit
        generation = validate_generation(settings.provider, body.model, generation)
        active.db.execute(
            "UPDATE sessions SET model=?,reasoning=?,generation=? WHERE id=?",
            (body.model, body.reasoning, json.dumps(generation), session_id),
        )
        return {"saved": True, "generation": generation}

    @app.post("/api/sessions/{session_id}/reset")
    async def reset(session_id: str, request: Request, owner=Depends(identity)):
        browser_session(request, owner, session_id)
        await current(request).reset(owner, session_id)
        return {"reset": True}

    def stream(turn, *, approvals=None):
        async def events():
            if approvals is not None:
                yield "data: " + json.dumps({"type": "approvals", "items": approvals}) + "\n\n"
            async for event in turn.events():
                yield "data: " + json.dumps(event) + "\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.post("/api/sessions/{session_id}/turn")
    async def turn(session_id: str, body: ChatInput, request: Request, owner=Depends(identity)):
        browser_session(request, owner, session_id)
        if not body.text.strip() and not body.files:
            raise ValueError("Enter a message or attach a file.")
        return stream(
            current(request).start(owner, session_id, body.text, body.files, mode=body.mode)
        )

    @app.post("/api/sessions/{session_id}/resume")
    async def resume(session_id: str, request: Request, owner=Depends(identity)):
        browser_session(request, owner, session_id)
        return stream(current(request).start(owner, session_id))

    @app.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def approve(
        session_id: str,
        approval_id: str,
        body: DecisionInput,
        request: Request,
        owner=Depends(identity),
    ):
        browser_session(request, owner, session_id)
        runtime = current(request)
        turn = runtime.start(owner, session_id, approval=(approval_id, body.approved))
        return stream(turn, approvals=runtime.pending(owner, session_id))

    @app.post("/api/files")
    async def upload(request: Request, file: UploadFile, owner=Depends(identity)):
        data = await file.read(settings.max_upload_bytes + 1)
        row = current(request).files.save(
            owner, file.filename or "upload", file.content_type or "application/octet-stream", data
        )
        return {k: row[k] for k in ("id", "name", "media_type", "size")}

    @app.get("/api/files/{file_id}")
    async def download(file_id: str, request: Request, owner=Depends(identity)):
        row = current(request).files.get(owner, file_id)
        return FileResponse(
            row["path"], filename=row["name"], media_type="application/octet-stream"
        )

    @app.post("/api/audio/transcribe")
    async def transcribe(body: TranscriptionInput, request: Request, owner=Depends(identity)):
        active = current(request)
        row = active.files.get(owner, body.file_id)
        if not row["media_type"].split(";", 1)[0].startswith("audio/"):
            raise ValueError("Select an audio file for transcription.")
        return {"text": await active.files.transcribe(owner, body.file_id)}

    @app.post("/api/audio/speech")
    async def speech(body: SpeechInput, request: Request, owner=Depends(identity)):
        row = await current(request).files.speech(owner, body.text)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @app.get("/api/notifications")
    async def notifications(request: Request, owner=Depends(identity)):
        return current(request).db.rows(
            "SELECT id,session,text,created,delivered FROM notifications WHERE owner=? ORDER BY created DESC LIMIT 50",
            (owner,),
        )

    @app.get("/api/activity")
    async def personal_activity(
        request: Request, days: Literal["7", "30", "90"] = "30", owner=Depends(identity)
    ):
        db = current(request).db
        # The authenticated token owns every aggregate, including administrator tokens.
        return {
            "activity": activity_summary(db, int(days), owner=owner),
            "totals": {
                **usage_summary(db, owner=owner),
                "conversations": db.one(
                    "SELECT COUNT(*) AS count FROM sessions WHERE owner=?", (owner,)
                )["count"],
            },
            "cost_per_conversation": db.rows(
                "SELECT s.id,s.owner,s.channel,COUNT(g.id) AS requests,SUM(g.cost) AS cost, "
                "COUNT(g.id)-COUNT(g.cost) AS unpriced_requests FROM sessions s "
                "LEFT JOIN usage g ON g.session=s.id AND g.owner=s.owner "
                "WHERE s.owner=? GROUP BY s.id ORDER BY s.updated DESC",
                (owner,),
            ),
            "usage": db.rows(
                "SELECT owner,model,COUNT(*) AS requests,COUNT(*)-COUNT(cost) AS unpriced_requests,"
                "SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,"
                "SUM(cache_tokens) AS cache_tokens,SUM(cost) AS cost FROM usage "
                "WHERE owner=? GROUP BY owner,model",
                (owner,),
            ),
        }

    @app.get("/api/dashboard")
    async def dashboard(
        request: Request, days: Literal["7", "30", "90"] = "30", owner=Depends(administrator)
    ):
        db = current(request).db
        return {
            "activity": activity_summary(db, int(days)),
            "totals": {
                **usage_summary(db),
                "users": db.one("SELECT COUNT(*) AS count FROM users")["count"],
                "conversations": db.one("SELECT COUNT(*) AS count FROM sessions")["count"],
            },
            "cost_per_user": db.rows(
                "SELECT u.id AS owner, COUNT(g.id) AS requests, SUM(g.cost) AS cost, "
                "COALESCE(SUM(g.input_tokens),0) AS input_tokens, "
                "COALESCE(SUM(g.output_tokens),0) AS output_tokens, "
                "COALESCE(SUM(g.cache_tokens),0) AS cache_tokens, "
                "COUNT(g.id)-COUNT(g.cost) AS unpriced_requests FROM users u "
                "LEFT JOIN usage g ON g.owner=u.id GROUP BY u.id ORDER BY u.id"
            ),
            "cost_per_conversation": db.rows(
                "SELECT s.id,s.owner,s.channel,COUNT(g.id) AS requests,SUM(g.cost) AS cost, "
                "COUNT(g.id)-COUNT(g.cost) AS unpriced_requests FROM sessions s "
                "LEFT JOIN usage g ON g.session=s.id AND g.owner=s.owner "
                "GROUP BY s.id ORDER BY s.updated DESC"
            ),
            "users": db.rows("SELECT id,created FROM users"),
            "sessions": db.rows(
                "SELECT id,owner,channel,model,status,updated FROM sessions ORDER BY updated DESC LIMIT 100"
            ),
            "usage": db.rows(
                "SELECT owner,model,COUNT(*) AS requests,COUNT(*)-COUNT(cost) AS unpriced_requests,"
                "SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,"
                "SUM(cache_tokens) AS cache_tokens,SUM(cost) AS cost FROM usage GROUP BY owner,model"
            ),
            "traces": db.rows(
                "SELECT id,owner,session,event,tool,status,created FROM traces ORDER BY id DESC LIMIT 100"
            ),
            "jobs": db.rows(
                "SELECT id,owner,kind,status,attempts,updated FROM jobs ORDER BY rowid DESC LIMIT 100"
            ),
            "scheduler_last_tick": getattr(
                getattr(request.app.state, "scheduler", None), "last_tick", None
            ),
        }

    @app.get("/api/logs")
    async def logs(owner=Depends(administrator)):
        path = settings.data_dir / "logs" / "theos.log"
        if not path.exists():
            return []
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 64000))
            lines = stream.read().decode(errors="replace").splitlines()
        result = []
        for line in lines[-100:]:
            try:
                result.append(json.loads(line))
            except ValueError:
                continue
        return result

    @app.get("/oauth/{service}/callback")
    async def callback(service: str, state: str, request: Request, code: str = ""):
        if service == "zepto":
            try:
                await current(request).zepto.finish_from_browser(
                    state, code, request.query_params.get("error", "")
                )
            except ValueError as error:
                raise HTTPException(400, str(error)) from error
            return HTMLResponse(
                "<!doctype html><title>Zepto connected</title>"
                "<p>Authorization received. Return to the workspace or private chat that started setup.</p>"
            )
        if service == "gitlab":
            await current(request).gitlab.callback(
                state, code, request.query_params.get("error", "")
            )
        else:
            await current(request).oauth.callback(service, state, code)
        return HTMLResponse(
            "<!doctype html><title>Account connected</title>"
            "<p>Account connected. Return to the workspace or private chat that started setup.</p>"
        )

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    async def index():
        page = (static / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace("{{AGENT_NAME}}", escape(settings.name)))

    return app
