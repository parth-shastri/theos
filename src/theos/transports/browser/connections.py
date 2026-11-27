"""Owner-bound browser connections and optional service availability."""

from typing import Annotated, Literal

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from theos.services import journeys
from theos.services.account_setup import ACCOUNT_LABELS, complete_setup, setup_status
from theos.services.errors import ServiceError
from theos.storage.account_access import browser_account_access


class ReturnURL(BaseModel):
    """Accept a short-lived localhost OAuth return outside model history."""

    url: str = Field(min_length=1, max_length=4000)


class CompleteSetup(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=100)


class CallPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reminders: bool = False
    approvals: bool = False


class ConnectionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = Field(default=None, max_length=100)
    source: Literal["chat", "connections"] = "connections"


class JourneyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(max_length=30)
    value: str = Field(default="", max_length=8000)
    revision: int = Field(ge=0)


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
        "calling": runtime.phone_calls.connections.status(owner),
    }


def register_connections(app, settings, current, identity):
    """Bind each account action to the token's owner, never a submitted user ID."""

    def authorize(request, owner, service):
        if not browser_account_access(settings, owner, current(request).db):
            raise PermissionError("Browser account access is required.")
        if service not in {"gmail", "calendar", "health", "zepto", "slack", "github"}:
            raise ValueError("Unknown account service.")

    @app.get("/api/journey")
    async def journey(request: Request, owner: Annotated[str, Depends(identity)]):
        return journeys.state(settings, current(request).db, owner)

    @app.post("/api/journey")
    async def journey_action(
        body: JourneyAction, request: Request, owner: Annotated[str, Depends(identity)]
    ):
        return journeys.update(
            settings, current(request).db, owner, body.action, body.value, body.revision
        )

    @app.get("/api/connections")
    async def connections(request: Request, owner: Annotated[str, Depends(identity)]):
        if not browser_account_access(settings, owner, current(request).db):
            raise PermissionError("Browser account access is required.")
        runtime = current(request)
        result = connection_status(runtime, owner)
        if result["calling"]["configured"]:
            try:
                result["calling"] = await runtime.phone_calls.connections.refresh(owner)
            except ServiceError as error:
                result["calling"]["error"] = str(error)
        return result

    def calls(request, owner):
        runtime = current(request)
        if not browser_account_access(settings, owner, runtime.db):
            raise PermissionError("Browser account access is required.")
        return runtime.phone_calls.connections

    @app.post("/api/calling/connect")
    async def connect_calls(request: Request, owner: Annotated[str, Depends(identity)]):
        return await calls(request, owner).start(owner)

    @app.post("/api/calling/test")
    async def test_calls(request: Request, owner: Annotated[str, Depends(identity)]):
        return calls(request, owner).test(owner, "browser")

    @app.post("/api/calling/retry")
    async def retry_calls(request: Request, owner: Annotated[str, Depends(identity)]):
        service = calls(request, owner)
        status = await service.refresh(owner)
        if status.get("test_status") == "accepted":
            raise ValueError("End the current Telegram call before another test.")
        return service.retry_test(owner)

    @app.post("/api/calling/confirm")
    async def confirm_calls(
        body: CallPreferences, request: Request, owner: Annotated[str, Depends(identity)]
    ):
        return calls(request, owner).confirm(owner, body.reminders, body.approvals)

    @app.post("/api/calling/preferences")
    async def call_preferences(
        body: CallPreferences, request: Request, owner: Annotated[str, Depends(identity)]
    ):
        return calls(request, owner).preferences(owner, body.reminders, body.approvals)

    @app.post("/api/calling/disconnect")
    async def disconnect_calls(request: Request, owner: Annotated[str, Depends(identity)]):
        return await calls(request, owner).disconnect(owner)

    @app.post("/api/connections/{service}/connect")
    async def connect(
        service: str,
        request: Request,
        owner: Annotated[str, Depends(identity)],
        body: ConnectionStart | None = None,
    ):
        authorize(request, owner, service)
        runtime = current(request)
        destination = body or ConnectionStart()
        journeys.remember_connection(
            runtime.db, owner, service, destination.session_id, destination.source
        )
        if service in {"github", "slack"}:
            result = await getattr(runtime, service).start(owner)
            journeys.bind_connection(runtime.db, owner, service, result.get("url", ""))
            return result
        if service == "zepto":
            return await runtime.zepto.connect_from_browser(owner)
        url = runtime.oauth.start(owner, service)
        journeys.bind_connection(runtime.db, owner, service, url)
        return {"status": "waiting", "url": url}

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
