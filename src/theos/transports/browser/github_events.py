"""Receive signed webhooks and manage private GitHub event notifications."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from theos.services.errors import ServiceError
from theos.services.github.notifications import MAX_BODY


class NotificationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    telegram: bool = False


def register_github_events(app, current, identity):
    @app.post("/webhooks/github")
    async def webhook(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "The GitHub webhook payload is too large.")
        try:
            result = current(request).github_events.receive(
                bytes(body),
                request.headers.get("x-hub-signature-256", ""),
                request.headers.get("x-github-delivery", ""),
                request.headers.get("x-github-event", ""),
            )
        except ServiceError as error:
            raise HTTPException(503, str(error)) from error
        except OverflowError as error:
            raise HTTPException(413, "The GitHub webhook payload is too large.") from error
        return JSONResponse(result, status_code=202)

    @app.put("/api/connections/github/notifications")
    async def configure(
        body: NotificationSettings, request: Request, owner: Annotated[str, Depends(identity)]
    ):
        return await current(request).github_events.configure(owner, body.enabled, body.telegram)

    @app.post("/api/connections/github/notifications/{notice_id}/read")
    async def mark_read(notice_id: str, request: Request, owner: Annotated[str, Depends(identity)]):
        return current(request).github_events.mark_read(owner, notice_id)
