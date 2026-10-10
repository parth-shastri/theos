"""Browser sign-in confirmed by the account's enrolled Telegram sender."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from theos.storage import browser_access
from theos.transports.telegram.polling import Telegram

SESSION_COOKIE = "theos-session"
PAIR_COOKIE = "theos-pairing"


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invite: str = Field(min_length=32, max_length=128)


def same_origin(request, settings):
    """Require a custom header and reject cross-origin cookie mutations."""
    origin = request.headers.get("Origin")
    allowed = {settings.web_url, str(request.base_url).rstrip("/")}
    if request.headers.get("X-Theos-Request") != "1" or (origin and origin not in allowed):
        raise HTTPException(403, "Use the web UI on this deployment to continue.")


def set_cookie(response, name, value, settings, max_age, path="/"):
    """Keep sign-in credentials out of JavaScript and cross-site requests."""
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        secure=urlsplit(settings.web_url).scheme == "https",
        httponly=True,
        samesite="strict",
    )


def register_auth(app, settings, current):
    """Register cookie sign-in without changing configured operator tokens."""

    @app.post("/api/onboarding/start")
    async def start(body: SignIn, request: Request):
        same_origin(request, settings)
        if not settings.web_url or not settings.telegram_token.get_secret_value():
            raise HTTPException(503, "Telegram web sign-in is not configured.")
        runtime = current(request)
        row, browser = browser_access.begin(settings, runtime.db, body.invite)
        try:
            await Telegram(runtime).send(
                int(row["owner"][9:]),
                f"A browser wants to open your Theos account. Code: {row['code']}\n"
                "Approve only if this code matches the browser you just opened. Otherwise, select Deny.",
                markup={
                    "inline_keyboard": [
                        [
                            {"text": "Approve browser", "callback_data": "web:" + row["id"]},
                            {"text": "Deny", "callback_data": "webdeny:" + row["id"]},
                        ]
                    ]
                },
            )
        except Exception:
            raise HTTPException(
                503, "The confirmation could not be delivered. Send /web in Telegram and try again."
            ) from None
        response = JSONResponse({"code": row["code"], "expires": row["expires"]})
        set_cookie(
            response,
            PAIR_COOKIE,
            browser,
            settings,
            browser_access.SIGNIN_SECONDS,
            "/api/onboarding",
        )
        return response

    @app.get("/api/onboarding/status")
    async def status(request: Request):
        row = browser_access.request_for_browser(
            settings, current(request).db, request.cookies.get(PAIR_COOKIE, "")
        )
        return {"state": row["state"], "expires": row["expires"], "code": row["code"]}

    @app.post("/api/onboarding/cancel")
    async def cancel(request: Request):
        same_origin(request, settings)
        current(request).db.execute(
            "UPDATE browser_signins SET state='denied' WHERE browser_hash=? "
            "AND state IN ('pending','approved')",
            (browser_access.fingerprint(request.cookies.get(PAIR_COOKIE, "")),),
        )
        response = JSONResponse({"canceled": True})
        response.delete_cookie(PAIR_COOKIE, path="/api/onboarding")
        return response

    @app.post("/api/onboarding/complete")
    async def complete(request: Request):
        same_origin(request, settings)
        db = current(request).db
        owner, token, session = browser_access.complete(
            settings, db, request.cookies.get(PAIR_COOKIE, "")
        )
        # Replace this browser's old session when switching accounts.
        db.execute(
            "DELETE FROM browser_credentials WHERE token_hash=? AND kind='session'",
            (browser_access.fingerprint(request.cookies.get(SESSION_COOKIE, "")),),
        )
        response = JSONResponse({"id": owner, "token": token})
        set_cookie(response, SESSION_COOKIE, session, settings, browser_access.SESSION_SECONDS)
        response.delete_cookie(PAIR_COOKIE, path="/api/onboarding")
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        same_origin(request, settings)
        current(request).db.execute(
            "DELETE FROM browser_credentials WHERE token_hash=? AND kind='session'",
            (browser_access.fingerprint(request.cookies.get(SESSION_COOKIE, "")),),
        )
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(SESSION_COOKIE)
        response.delete_cookie(PAIR_COOKIE, path="/api/onboarding")
        return response
