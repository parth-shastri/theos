"""Owner-bound browser connections and optional service availability."""

import time
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from theos.storage.account_access import browser_account_access


class ReturnURL(BaseModel):
    """Accept a short-lived localhost OAuth return outside model history."""

    url: str = Field(min_length=1, max_length=4000)


def connection_status(runtime, owner):
    """Expose availability and owner connection state without credentials."""
    settings = runtime.settings
    accounts = []
    for service, label in (
        ("gmail", "Gmail"),
        ("health", "Google Health"),
        ("zepto", "Zepto"),
        ("slack", "Slack"),
    ):
        if service == "slack":
            accounts.append(runtime.slack.status(owner))
            continue
        connected = (
            runtime.zepto.connected(owner)
            if service == "zepto"
            else bool(
                runtime.db.one(
                    "SELECT 1 FROM credentials WHERE owner=? AND service=?", (owner, service)
                )
            )
        )
        setup = (
            runtime.zepto.connection_status(owner)
            if service == "zepto"
            else {
                "status": "waiting"
                if runtime.db.one(
                    "SELECT 1 FROM oauth_states WHERE owner=? AND service=? AND expires>?",
                    (owner, service, time.time()),
                )
                else "idle"
            }
        )
        accounts.append(
            {
                "id": service,
                "name": label,
                "configured": bool(settings.zepto_url)
                if service == "zepto"
                else getattr(settings, service).enabled,
                "connected": connected,
                "setup": setup,
            }
        )
    services = [
        ("sandbox", "Sandbox", settings.sandbox.enabled),
        ("memory", "Personal memory", settings.memory.enabled),
        ("search", "Web search", bool(settings.exa_key or settings.brave_key)),
        ("storage", "Cloud file storage", bool(settings.storage.endpoint)),
        ("transcription", "Voice transcription", bool(settings.transcription_url)),
        ("tts", "Speech playback", bool(settings.kokoro_url)),
        ("weather", "Weather", True),
        ("skills", "Skill resources", settings.skills_dir is not None),
    ]
    return {
        "accounts": accounts,
        "services": [
            {"id": service, "name": name, "configured": bool(enabled)}
            for service, name, enabled in services
        ],
    }


def register_connections(app, settings, current, identity):
    """Bind each account action to the token's owner, never a submitted user ID."""

    def authorize(request, owner, service):
        if not browser_account_access(settings, owner, current(request).db):
            raise PermissionError("Browser account access is required.")
        if service not in {"gmail", "health", "zepto", "slack"}:
            raise ValueError("Unknown account service.")

    @app.get("/api/connections")
    async def connections(request: Request, owner: Annotated[str, Depends(identity)]):
        if not browser_account_access(settings, owner, current(request).db):
            raise PermissionError("Browser account access is required.")
        return connection_status(current(request), owner)

    @app.post("/api/connections/{service}/connect")
    async def connect(service: str, request: Request, owner: Annotated[str, Depends(identity)]):
        authorize(request, owner, service)
        runtime = current(request)
        if service == "slack":
            return await runtime.slack.start(owner)
        if service == "zepto":
            return await runtime.zepto.connect_from_browser(owner)
        return {"status": "waiting", "url": runtime.oauth.start(owner, service)}

    @app.post("/api/connections/{service}/disconnect")
    async def disconnect(service: str, request: Request, owner: Annotated[str, Depends(identity)]):
        authorize(request, owner, service)
        runtime = current(request)
        if service == "slack":
            return await runtime.slack.disconnect(owner)
        if service == "zepto":
            await runtime.zepto.disconnect(owner)
            return {"disconnected": True}
        return await runtime.oauth.disconnect(owner, service)

    @app.post("/api/connections/zepto/finish")
    async def finish(body: ReturnURL, request: Request, owner: Annotated[str, Depends(identity)]):
        authorize(request, owner, "zepto")
        await current(request).zepto.finish_return_url(owner, body.url)
        return {"accepted": True}
