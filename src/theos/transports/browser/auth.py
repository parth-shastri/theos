"""Opaque browser sessions for configured tokens and Telegram-confirmed sign-in."""

import hmac
from ipaddress import ip_address
from urllib.parse import urlsplit

from anyio import CapacityLimiter, to_thread
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from theos.services.preferences.tools import preferences
from theos.storage import browser_access, browser_passwords
from theos.transports.telegram.polling import Telegram

SESSION_COOKIE = "theos-session"
PAIR_COOKIE = "theos-pairing"


class TokenSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr


class PasswordSignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: str = Field(min_length=1, max_length=256)
    password: SecretStr


class PasswordSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr
    confirmation: SecretStr


async def password_body(request, model):
    """Return a fixed error when parsing a request that contains a password."""
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 8192:
            raise HTTPException(413, "The password request is too large.")
        data.extend(chunk)
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, "Check the password form and try again.") from None


def login_source(request, settings):
    source = request.client.host if request.client else "local"
    if settings.frontend_secret.get_secret_value() and request.headers.get("X-Theos-Client-IP"):
        try:
            source = str(ip_address(request.headers["X-Theos-Client-IP"]))
        except ValueError:
            pass
    return source


def require_login_limit(db, *sources):
    if any(not browser_access.check_login_limit(db, source) for source in sources):
        raise HTTPException(
            429,
            "Too many sign-in attempts. Try again in 15 minutes.",
            headers={"Retry-After": "900"},
        )


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
    # Bound memory use on the Pi. Hash off the event loop so chat and polling can continue.
    password_work = CapacityLimiter(1)

    def signed_in(session):
        response = JSONResponse({"signed_in": True})
        set_cookie(response, SESSION_COOKIE, session, settings, browser_access.SESSION_SECONDS)
        clear_cookie(response, PAIR_COOKIE, settings, "/api/onboarding")
        return response

    def password_account(request):
        db = current(request).db
        session = cookie_value(request, SESSION_COOKIE, settings)
        owner = (
            browser_access.credential_owner(settings, db, session, "session") if session else None
        )
        if not owner:
            raise HTTPException(401, "Sign in to manage your password.")
        return db, owner, session

    @app.post("/api/auth/login")
    async def login(body: TokenSignIn, request: Request):
        same_origin(request, settings)
        db = current(request).db
        source = login_source(request, settings)
        require_login_limit(db, source)
        token = body.token.get_secret_value()
        owner = browser_access.token_owner(settings, db, token) if 32 <= len(token) <= 256 else None
        if not owner:
            browser_access.record_login_failure(db, source)
            raise HTTPException(401, "The access token is invalid or expired.")
        with db.transaction():
            session = browser_access.replace_session(
                settings, db, owner, cookie_value(request, SESSION_COOKIE, settings), token
            )
        return signed_in(session)

    @app.post("/api/auth/password/login")
    async def password_login(request: Request):
        same_origin(request, settings)
        body = await password_body(request, PasswordSignIn)
        db = current(request).db
        owner = body.account
        source = login_source(request, settings)
        account = "password:" + owner
        async with password_work:
            require_login_limit(db, source, account)
            row = browser_passwords.for_owner(settings, db, owner)
            valid = await to_thread.run_sync(
                browser_passwords.verify, body.password.get_secret_value(), row
            )
            if not valid or row != browser_passwords.for_owner(settings, db, owner):
                browser_access.record_login_failure(db, source)
                browser_access.record_login_failure(db, account)
                raise HTTPException(401, "The account ID or password is incorrect.")
            token = settings.users.get(owner)
            with db.transaction():
                session = browser_access.replace_session(
                    settings,
                    db,
                    owner,
                    cookie_value(request, SESSION_COOKIE, settings),
                    token.get_secret_value() if token is not None else None,
                    password_login=True,
                )
        return signed_in(session)

    @app.get("/api/auth/password")
    async def password_status(request: Request):
        frontend_access(request, settings)
        db, owner, _ = password_account(request)
        return {"account": owner, "enabled": bool(browser_passwords.for_owner(settings, db, owner))}

    @app.post("/api/auth/password")
    async def save_password(request: Request):
        same_origin(request, settings)
        body = await password_body(request, PasswordSetup)
        async with password_work:
            db, owner, session = password_account(request)
            profile = preferences(db, owner, settings.timezone)
            salt, digest = await to_thread.run_sync(
                browser_passwords.create,
                body.password.get_secret_value(),
                body.confirmation.get_secret_value(),
                [
                    owner,
                    owner.removeprefix("telegram:"),
                    settings.name,
                    profile.get("display_name", ""),
                ],
            )
            password_account(request)
            with db.transaction():
                browser_passwords.save(settings, db, owner, salt, digest)
                browser_passwords.revoke_other_sessions(db, owner, session)
        return {"account": owner, "enabled": True}

    @app.delete("/api/auth/password")
    async def remove_password(request: Request):
        same_origin(request, settings)
        async with password_work:
            db, owner, session = password_account(request)
            with db.transaction():
                db.execute("DELETE FROM browser_passwords WHERE owner=?", (owner,))
                browser_passwords.revoke_other_sessions(db, owner, session)
        return {"account": owner, "enabled": False}

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
                (
                    "A browser wants to manage your Theos password."
                    if row["password_setup"]
                    else "A browser wants to open your Theos account."
                )
                + f" Code: {row['code']}\n"
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
            settings,
            db,
            cookie_value(request, PAIR_COOKIE, settings),
            previous=cookie_value(request, SESSION_COOKIE, settings),
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
