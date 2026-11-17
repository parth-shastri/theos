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
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import Path as PathParam

from .settings import Settings

MAX_AUDIO = 2 * 1024 * 1024
logger = logging.getLogger("theos.calling")
CallID = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9_:.-]{1,160}$")]


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
        # Accepted work can have reached Telegram before a crash. Never repeat it.
        db.execute("UPDATE calls SET status='uncertain' WHERE status='accepted'")
        for path in settings.data_dir.glob("clip-*.mp3"):
            path.unlink()
        app.state.db = db
        app.state.task = None
        if caller is None:
            from .telegram import TelegramCaller

            app.state.caller = TelegramCaller(settings)
        else:
            app.state.caller = caller
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

    async def deliver(id, recipient, audio):
        path = settings.data_dir / ("clip-" + secrets.token_hex(16) + ".mp3")
        status = "uncertain"
        try:
            with path.open("xb") as output:
                path.chmod(0o600)
                output.write(audio)
            await app.state.caller.play(recipient, path)
            status = "completed"
        except asyncio.CancelledError:
            raise
        except Exception:
            # A Telegram error can follow an accepted dial. Log no account or media data.
            logger.warning("telegram_call_uncertain")
        finally:
            path.unlink(missing_ok=True)
            app.state.db.execute("UPDATE calls SET status=? WHERE id=?", (status, id))

    @app.post("/v1/calls/{id}", status_code=202, dependencies=[Depends(authenticate)])
    async def call(
        id: CallID,
        request: Request,
        recipient: Annotated[int, Query(gt=0)],
        expires: float,
    ):
        if recipient not in settings.recipients:
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
            if existing["recipient"] != recipient or existing["digest"] != digest:
                raise HTTPException(409, "The call ID is already in use.")
            return {"id": id, "status": existing["status"]}
        if app.state.task and not app.state.task.done():
            raise HTTPException(409, "The calling account is busy.")
        count = db.execute("SELECT count(*) FROM calls WHERE created>?", (now - 86400,)).fetchone()[
            0
        ]
        if count >= settings.daily_limit:
            raise HTTPException(429, "The daily call limit was reached.")
        db.execute("INSERT INTO calls VALUES (?,?,?,?,?)", (id, recipient, digest, now, "accepted"))
        # A single worker claims the row before starting the external effect.
        app.state.task = asyncio.create_task(deliver(id, recipient, bytes(audio)))
        return {"id": id, "status": "accepted"}

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
