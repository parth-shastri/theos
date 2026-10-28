"""Private browser sign-in controls. Input values never enter conversation history."""

import asyncio
import base64
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from theos.storage.account_access import browser_account_access


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["open", "refresh", "click", "type", "press", "scroll"]
    url: str = Field(default="", max_length=4000)
    text: SecretStr = SecretStr("")
    key: Literal["Enter", "Tab", "Shift+Tab", "Backspace", "Escape", "ArrowUp", "ArrowDown"] = (
        "Enter"
    )
    x: int = Field(default=0, ge=0, le=10000)
    y: int = Field(default=0, ge=0, le=10000)
    direction: Literal["up", "down"] = "down"


def register_managed_browser(app, current, identity):
    def authorized(request, owner):
        runtime = current(request)
        if not browser_account_access(runtime.settings, owner, runtime.db):
            raise PermissionError("Browser account access is required.")
        if not runtime.settings.sandbox.enabled:
            raise ValueError("Configure the sandbox service before browser sign-in.")
        return runtime

    @app.get("/api/connections/browser/status")
    async def status(request: Request, owner: Annotated[str, Depends(identity)]):
        return authorized(request, owner).browsers.status(owner)

    @app.post("/api/connections/browser/action")
    async def action(
        body: BrowserAction, request: Request, owner: Annotated[str, Depends(identity)]
    ):
        runtime = authorized(request, owner)
        browser = runtime.browsers
        # User input and screenshots stay on this authenticated route, outside tool traces.
        async with browser.locks.setdefault(owner, asyncio.Lock()):
            sandbox = await browser.prepare(owner)
            await browser.select(sandbox, "manual-login")
            args = None
            if body.action == "open":
                uri = urlsplit(body.url)
                if (
                    uri.scheme not in {"http", "https"}
                    or not uri.hostname
                    or uri.username
                    or uri.password
                ):
                    raise ValueError("Use an HTTP or HTTPS page URL without credentials.")
                args = ["open", body.url]
            elif body.action == "click":
                await browser.cli(sandbox, ["mouse", "move", str(body.x), str(body.y)])
                await browser.cli(sandbox, ["mouse", "down", "left"])
                args = ["mouse", "up", "left"]
            elif body.action == "type":
                text = body.text.get_secret_value()
                if len(text) > 4000:
                    raise ValueError("The input exceeds 4,000 characters.")
                args = ["keyboard", "inserttext", text]
            elif body.action == "press":
                args = ["press", body.key]
            elif body.action == "scroll":
                args = ["scroll", body.direction, "500"]
            try:
                result = await browser.cli(sandbox, args) if args else {"success": True}
                screenshot = await browser.cli(
                    sandbox, ["screenshot", "/tmp/theos-browser/login.png"]
                )
                if not screenshot.get("success"):
                    raise ValueError("The browser screenshot is unavailable.")
                data = await browser.boxes.read_bytes(sandbox, "/tmp/theos-browser/login.png")
                snapshot = await browser.cli(sandbox, ["snapshot", "-i"])
                return {
                    "success": bool(result.get("success")),
                    "image": "data:image/png;base64," + base64.b64encode(data).decode(),
                    "snapshot": snapshot.get("data", {}),
                }
            finally:
                await browser.save(owner, sandbox)

    @app.post("/api/connections/browser/disconnect")
    async def disconnect(request: Request, owner: Annotated[str, Depends(identity)]):
        runtime = authorized(request, owner)
        await runtime.browsers.disconnect(owner)
        return {"disconnected": True}
