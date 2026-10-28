"""Owner-bound browser connections and optional service availability."""

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from theos.services.account_setup import ACCOUNT_LABELS, complete_setup, setup_status
from theos.storage.account_access import browser_account_access


class ReturnURL(BaseModel):
    """Accept a short-lived localhost OAuth return outside model history."""

    url: str = Field(min_length=1, max_length=4000)


class CompleteSetup(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=100)


def connection_status(runtime, owner):
    """Expose availability and owner connection state without credentials."""
    settings = runtime.settings
    accounts = []
    for service, label in ACCOUNT_LABELS:
        if service in {"github", "slack"}:
            account = getattr(runtime, service).status(owner)
            if service == "github":
                account["notifications"] = runtime.github_events.status(owner)
            accounts.append(account)
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
            else runtime.oauth.connection_status(owner, service)
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
        "accounts": [account for account in accounts if account["configured"]],
        "onboarding": setup_status(settings, runtime.db, owner, runtime.zepto),
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
        if service not in {"gmail", "health", "zepto", "slack", "github"}:
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
        if service in {"github", "slack"}:
            return await getattr(runtime, service).start(owner)
        if service == "zepto":
            return await runtime.zepto.connect_from_browser(owner)
        return {"status": "waiting", "url": runtime.oauth.start(owner, service)}

    @app.post("/api/connections/onboarding")
    async def finish_setup(
        body: CompleteSetup, request: Request, owner: Annotated[str, Depends(identity)]
    ):
        if not browser_account_access(settings, owner, current(request).db):
            raise PermissionError("Browser account access is required.")
        return complete_setup(
            settings, current(request).db, owner, body.display_name, body.timezone
        )

    @app.post("/api/connections/{service}/cancel")
    async def cancel(service: str, request: Request, owner: Annotated[str, Depends(identity)]):
        authorize(request, owner, service)
        runtime = current(request)
        if service in {"github", "slack"}:
            await getattr(runtime, service).cancel(owner)
        elif service == "zepto":
            await runtime.zepto.cancel(owner)
        else:
            await runtime.oauth.cancel(owner, service)
        return {"cancelled": True}

    @app.post("/api/connections/{service}/disconnect")
    async def disconnect(service: str, request: Request, owner: Annotated[str, Depends(identity)]):
        authorize(request, owner, service)
        runtime = current(request)
        if service in {"github", "slack"}:
            if service == "github":
                runtime.github_events.disable(owner)
            return await getattr(runtime, service).disconnect(owner)
        if service == "zepto":
            await runtime.zepto.disconnect(owner)
            return {"disconnected": True}
        return await runtime.oauth.disconnect(owner, service)

    @app.post("/api/connections/zepto/finish")
    async def finish(body: ReturnURL, request: Request, owner: Annotated[str, Depends(identity)]):
        authorize(request, owner, "zepto")
        await current(request).zepto.finish_return_url(owner, body.url)
        return {"accepted": True}
