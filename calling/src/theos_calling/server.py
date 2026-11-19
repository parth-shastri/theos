"""Accept bounded audio from Theos and place each requested Telegram call once."""

import argparse
import asyncio
import hashlib
import logging
import math
import os
import secrets
import sqlite3
import time
import traceback
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .connections import Connections
from .dialogue import Dialogue
from .settings import Settings

MAX_AUDIO = 2 * 1024 * 1024
logger = logging.getLogger("theos.calling")
CallID = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_:.-]{1,160}$")]
ConnectionID = Annotated[str, PathParam(pattern=r"^[a-f0-9]{32}$")]


class ConnectionRequest(BaseModel):
    expected_recipient: int | None = Field(default=None, gt=0)


def create_app(settings: Settings, *, caller=None):
    @asynccontextmanager
    async def lifespan(app):
        settings.prepare_directory()
        db = sqlite3.connect(settings.data_dir / "calls.sqlite3", isolation_level=None)
        db.row_factory = sqlite3.Row
        (settings.data_dir / "calls.sqlite3").chmod(0o600)
        db.execute(
            "CREATE TABLE IF NOT EXISTS calls "
            "(id TEXT PRIMARY KEY,recipient INTEGER,digest TEXT,created REAL,status TEXT)"
        )
        if "interactive" not in {row["name"] for row in db.execute("PRAGMA table_info(calls)")}:
            db.execute("ALTER TABLE calls ADD COLUMN interactive INTEGER NOT NULL DEFAULT 0")
        # Accepted work can have reached Telegram before a crash. Never repeat it.
        db.execute("UPDATE calls SET status='uncertain' WHERE status='accepted'")
        for path in settings.data_dir.glob("clip-*.mp3"):
            path.unlink()
        app.state.db = db
        app.state.task = None
        app.state.dialogue = None
        if caller is None:
            from .telegram import TelegramCaller

            app.state.caller = TelegramCaller(settings)
        else:
            app.state.caller = caller
        app.state.connections = Connections(db, settings.key.get_secret_value(), app.state.caller)
        app.state.caller.connection_handler = app.state.connections.receive
        try:
            await app.state.caller.start()
            yield
        finally:
            if app.state.task:
                app.state.task.cancel()
                await asyncio.gather(app.state.task, return_exceptions=True)
            await app.state.caller.close()
            db.close()

    app = FastAPI(lifespan=lifespan)

    async def authenticate(request: Request):
        supplied = request.headers.get("authorization", "").encode()
        expected = ("Bearer " + settings.key.get_secret_value()).encode()
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(401, "Calling authentication required.")

    @app.get("/ready")
    async def ready():
        return {"status": "ok"}

    @app.post("/v1/connections/{id}", dependencies=[Depends(authenticate)])
    async def connect(id: ConnectionID, body: ConnectionRequest):
        return app.state.connections.start(id, body.expected_recipient)

    @app.get("/v1/connections/{id}", dependencies=[Depends(authenticate)])
    async def connection(id: ConnectionID):
        return app.state.connections.status(id)

    @app.delete("/v1/connections/{id}", dependencies=[Depends(authenticate)])
    async def disconnect(id: ConnectionID):
        app.state.connections.disable(id)
        return {"status": "disabled"}

    async def deliver(id, recipient, audio, dialogue=None, expires=None):
        path = settings.data_dir / ("clip-" + secrets.token_hex(16) + ".mp3")
        feedback_path = settings.data_dir / ("clip-" + secrets.token_hex(16) + ".mp3")
        status = "uncertain"
        try:
            with path.open("xb") as output:
                path.chmod(0o600)
                output.write(audio)
            if dialogue:

                async def respond(answer):
                    feedback = await dialogue.answer(answer)
                    if feedback:
                        with feedback_path.open("xb") as output:
                            feedback_path.chmod(0o600)
                            output.write(feedback)
                        return feedback_path
                    return None

                async with asyncio.timeout(max(0.001, min(150, expires - time.time()))):
                    await app.state.caller.interact(recipient, path, respond)
            else:
                await app.state.caller.play(recipient, path)
            status = "completed"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # A Telegram error can follow an accepted dial. Log no account or media data.
            frames = traceback.extract_tb(error.__traceback__)[-6:]
            logger.warning(
                "telegram_call_uncertain error_type=%s frames=%s",
                type(error).__name__,
                ">".join(f"{frame.name}:{frame.lineno}" for frame in frames),
            )
        finally:
            path.unlink(missing_ok=True)
            feedback_path.unlink(missing_ok=True)
            if dialogue:
                dialogue.close()
                if app.state.dialogue is dialogue:
                    app.state.dialogue = None
            app.state.db.execute("UPDATE calls SET status=? WHERE id=?", (status, id))

    @app.post("/v1/calls/{id}", status_code=202, dependencies=[Depends(authenticate)])
    async def call(
        id: CallID,
        request: Request,
        recipient: Annotated[int, Query(gt=0)],
        expires: float,
        interactive: bool = False,
    ):
        if interactive and not settings.spoken_approvals:
            raise HTTPException(409, "Spoken approval calls are not enabled.")
        if recipient not in settings.recipients and not app.state.connections.permitted(recipient):
            raise HTTPException(403, "Call recipient is unavailable.")
        now = time.time()
        if not math.isfinite(expires) or not now < expires <= now + 901:
            raise HTTPException(410, "The call request expired.")
        if request.headers.get("content-type", "").split(";", 1)[0] != "audio/mpeg":
            raise HTTPException(415, "Send MP3 audio.")
        audio = bytearray()
        async for chunk in request.stream():
            if len(audio) + len(chunk) > MAX_AUDIO:
                raise HTTPException(413, "Call audio exceeds the size limit.")
            audio.extend(chunk)
        if expires <= time.time():
            raise HTTPException(410, "The call request expired.")
        if not audio:
            raise HTTPException(400, "Send nonempty MP3 audio.")
        db = app.state.db
        digest = hashlib.sha256(audio).hexdigest()
        existing = db.execute("SELECT * FROM calls WHERE id=?", (id,)).fetchone()
        if existing:
            if (
                existing["recipient"] != recipient
                or existing["digest"] != digest
                or bool(existing["interactive"]) != interactive
            ):
                raise HTTPException(409, "The call ID is already in use.")
            return {"id": id, "status": existing["status"]}
        if app.state.task and not app.state.task.done():
            raise HTTPException(409, "The calling account is busy.")
        count = db.execute("SELECT count(*) FROM calls WHERE created>?", (now - 86400,)).fetchone()[
            0
        ]
        if count >= settings.daily_limit:
            raise HTTPException(429, "The daily call limit was reached.")
        db.execute(
            "INSERT INTO calls(id,recipient,digest,created,status,interactive) VALUES (?,?,?,?,?,?)",
            (id, recipient, digest, now, "accepted", interactive),
        )
        dialogue = Dialogue(id, recipient) if interactive else None
        if dialogue:
            dialogue.expires = expires
            app.state.dialogue = dialogue
        # A single worker claims the row before starting the external effect.
        app.state.task = asyncio.create_task(
            deliver(id, recipient, bytes(audio), dialogue, expires)
        )
        return {"id": id, "status": "accepted"}

    def active_dialogue(id):
        dialogue = app.state.dialogue
        if not dialogue or dialogue.id != id or dialogue.expires <= time.time():
            raise HTTPException(410, "The spoken response is unavailable.")
        return dialogue

    @app.get("/v1/calls/{id}/response", dependencies=[Depends(authenticate)])
    async def response(id: CallID):
        dialogue = active_dialogue(id)
        if dialogue.response is None:
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        return Response(
            dialogue.response, media_type="audio/wav", headers={"Cache-Control": "no-store"}
        )

    @app.post("/v1/calls/{id}/finish", dependencies=[Depends(authenticate)])
    async def finish(id: CallID, request: Request):
        dialogue = active_dialogue(id)
        if request.headers.get("content-type", "").split(";", 1)[0] != "audio/mpeg":
            raise HTTPException(415, "Send MP3 audio.")
        audio = bytearray()
        async for chunk in request.stream():
            if len(audio) + len(chunk) > MAX_AUDIO:
                raise HTTPException(413, "Call audio exceeds the size limit.")
            audio.extend(chunk)
        if not audio:
            raise HTTPException(400, "Send nonempty MP3 audio.")
        dialogue.finish(bytes(audio))
        return {"status": "accepted"}

    @app.get("/v1/calls/{id}", dependencies=[Depends(authenticate)])
    async def status(id: CallID):
        row = app.state.db.execute("SELECT status FROM calls WHERE id=?", (id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Call not found.")
        return {"id": id, "status": row["status"]}

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env", help="Private gateway environment file")
    args = parser.parse_args()
    os.umask(0o077)
    settings = Settings(_env_file=args.env_file)
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port, workers=1, access_log=False
    )
