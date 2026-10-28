"""Opaque browser sessions for configured tokens and Telegram-confirmed sign-in."""

import hmac
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from theos.storage import browser_access
from theos.transports.telegram.polling import Telegram

SESSION_COOKIE = "theos-session"
PAIR_COOKIE = "theos-pairing"


class TokenSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


def cookie_name(name, settings):
    if urlsplit(settings.web_url).scheme != "https":
        return name
    return ("__Host-" if name == SESSION_COOKIE else "__Secure-") + name


def cookie_value(request, name, settings):
    return request.cookies.get(cookie_name(name, settings), "")


def frontend_access(request, settings):
    secret = settings.frontend_secret.get_secret_value()
    supplied = request.headers.get("X-Theos-Frontend-Secret", "")
    if secret and not hmac.compare_digest(secret.encode(), supplied.encode()):
        raise HTTPException(403, "Use the web UI on this deployment to continue.")


class SignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invite: str = Field(min_length=32, max_length=128)


def same_origin(request, settings):
    """Require a custom header and reject cross-origin cookie mutations."""
    frontend_access(request, settings)
    origin = request.headers.get("Origin")
    allowed = {settings.web_url, str(request.base_url).rstrip("/")}
    if request.headers.get("X-Theos-Request") != "1" or (origin and origin not in allowed):
        raise HTTPException(403, "Use the web UI on this deployment to continue.")


def set_cookie(response, name, value, settings, max_age, path="/"):
    """Keep sign-in credentials out of JavaScript and cross-site requests."""
    response.set_cookie(
        cookie_name(name, settings),
        value,
        max_age=max_age,
        path=path,
        secure=urlsplit(settings.web_url).scheme == "https",
        httponly=True,
        samesite="strict",
    )


def clear_cookie(response, name, settings, path="/"):
    response.delete_cookie(
        cookie_name(name, settings),
        path=path,
        secure=urlsplit(settings.web_url).scheme == "https",
        httponly=True,
        samesite="strict",
    )


def register_auth(app, settings, current):
    """Register cookie sign-in without changing configured operator tokens."""

    @app.post("/api/auth/login")
    async def login(body: TokenSignIn, request: Request):
        same_origin(request, settings)
        db = current(request).db
        source = request.client.host if request.client else "local"
        if settings.frontend_secret.get_secret_value() and request.headers.get("X-Theos-Client-IP"):
            try:
                source = str(ip_address(request.headers["X-Theos-Client-IP"]))
            except ValueError:
                pass
        if not browser_access.check_login_limit(db, source):
            raise HTTPException(
                429,
                "Too many sign-in attempts. Try again in 15 minutes.",
                headers={"Retry-After": "900"},
            )
        token = body.token.get_secret_value()
        owner = browser_access.token_owner(settings, db, token) if 32 <= len(token) <= 256 else None
        if not owner:
            browser_access.record_login_failure(db, source)
            raise HTTPException(401, "The access token is invalid or expired.")
        with db.transaction():
            db.execute(
                "DELETE FROM browser_credentials WHERE token_hash=? AND kind='session'",
                (browser_access.fingerprint(cookie_value(request, SESSION_COOKIE, settings)),),
            )
            session = browser_access.issue_session(settings, db, owner, token)
        response = JSONResponse({"signed_in": True})
        set_cookie(response, SESSION_COOKIE, session, settings, browser_access.SESSION_SECONDS)
        clear_cookie(response, PAIR_COOKIE, settings, "/api/onboarding")
        return response

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
            settings, current(request).db, cookie_value(request, PAIR_COOKIE, settings)
        )
        return {"state": row["state"], "expires": row["expires"], "code": row["code"]}

    @app.post("/api/onboarding/cancel")
    async def cancel(request: Request):
        same_origin(request, settings)
        current(request).db.execute(
            "UPDATE browser_signins SET state='denied' WHERE browser_hash=? "
            "AND state IN ('pending','approved')",
            (browser_access.fingerprint(cookie_value(request, PAIR_COOKIE, settings)),),
        )
        response = JSONResponse({"canceled": True})
        clear_cookie(response, PAIR_COOKIE, settings, "/api/onboarding")
        return response

    @app.post("/api/onboarding/complete")
    async def complete(request: Request):
        same_origin(request, settings)
        db = current(request).db
        owner, token, session = browser_access.complete(
            settings, db, cookie_value(request, PAIR_COOKIE, settings)
        )
        # Replace this browser's old session when switching accounts.
        db.execute(
            "DELETE FROM browser_credentials WHERE token_hash=? AND kind='session'",
            (browser_access.fingerprint(cookie_value(request, SESSION_COOKIE, settings)),),
        )
        response = JSONResponse({"id": owner, "token": token})
        set_cookie(response, SESSION_COOKIE, session, settings, browser_access.SESSION_SECONDS)
        clear_cookie(response, PAIR_COOKIE, settings, "/api/onboarding")
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        same_origin(request, settings)
        current(request).db.execute(
            "DELETE FROM browser_credentials WHERE token_hash=? AND kind='session'",
            (browser_access.fingerprint(cookie_value(request, SESSION_COOKIE, settings)),),
        )
        response = JSONResponse({"signed_out": True})
        clear_cookie(response, SESSION_COOKIE, settings)
        clear_cookie(response, PAIR_COOKIE, settings, "/api/onboarding")
        return response
