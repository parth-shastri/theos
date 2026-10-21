"""Browser sessions protect existing owners without retaining access tokens in JavaScript."""

import time

import httpx
from pydantic import SecretStr

from theos.server import create_app
from theos.storage import browser_access

HEADERS = {"X-Theos-Request": "1", "Origin": "https://theos.test"}


def browser(runtime):
    runtime.settings.web_url = "https://theos.test"
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="https://theos.test",
        headers=HEADERS,
    )


async def test_login_issues_protected_opaque_session_and_logout_revokes_it(runtime):
    async with browser(runtime) as client:
        assert (await client.get("/api/me")).status_code == 401
        result = await client.post("/api/auth/login", json={"token": "a" * 32})
        assert result.status_code == 200
        assert result.json() == {"signed_in": True}
        session = client.cookies.get("__Host-theos-session")
        assert session and session != "a" * 32
        cookie = result.headers.get_list("set-cookie")[0]
        assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"))
        assert "Domain=" not in cookie
        assert result.headers["cache-control"] == "no-store"
        assert (await client.get("/api/me")).json()["id"] == "alice"
        assert (await client.get("/api/dashboard")).status_code == 200
        stored = runtime.db.one("SELECT * FROM browser_credentials WHERE kind='session'")
        assert stored["token_hash"] == browser_access.fingerprint(session)
        assert session not in str(stored)
        assert (await client.post("/api/auth/logout")).status_code == 200
        assert (await client.get("/api/me")).status_code == 401
        client.cookies.set("__Host-theos-session", session, domain="theos.test", path="/")
        assert (await client.get("/api/me")).status_code == 401


async def test_cookie_mutations_reject_csrf_and_login_rotates_session(runtime):
    async with browser(runtime) as client:
        for headers in ({"X-Theos-Request": ""}, {"Origin": "https://evil.test"}):
            result = await client.post("/api/auth/login", json={"token": "a" * 32}, headers=headers)
            assert result.status_code == 403
        await client.post("/api/auth/login", json={"token": "a" * 32})
        old = client.cookies.get("__Host-theos-session")
        await client.post("/api/auth/login", json={"token": "b" * 32})
        assert client.cookies.get("__Host-theos-session") != old
        assert (await client.get("/api/me")).json()["id"] == "bob"
        assert (await client.get("/api/dashboard")).status_code == 403
        assert browser_access.credential_owner(runtime.settings, runtime.db, old, "session") is None
        assert (
            await client.post("/api/sessions", json={}, headers={"Origin": "https://evil.test"})
        ).status_code == 403


async def test_session_idle_and_absolute_expiry_and_configured_token_rotation(runtime):
    async with browser(runtime) as client:

        async def sign_in():
            result = await client.post("/api/auth/login", json={"token": "a" * 32})
            assert result.status_code == 200

        await sign_in()
        runtime.db.execute(
            "UPDATE browser_session_metadata SET last_used=?",
            (time.time() - browser_access.SESSION_IDLE_SECONDS - 1,),
        )
        assert (await client.get("/api/me")).status_code == 401
        await sign_in()
        runtime.db.execute("UPDATE browser_credentials SET expires=0 WHERE kind='session'")
        assert (await client.get("/api/me")).status_code == 401
        await sign_in()
        runtime.settings.users["alice"] = SecretStr("c" * 32)
        assert (await client.get("/api/me")).status_code == 401
        runtime.settings.users.pop("alice")
        assert (await client.get("/api/me")).status_code == 401


async def test_login_rate_limit_uses_persistent_records_and_generic_failures(runtime):
    async with browser(runtime) as client:
        for _ in range(20):
            result = await client.post("/api/auth/login", json={"token": "unknown-secret"})
            assert result.status_code == 401
            assert "unknown-secret" not in result.text
        result = await client.post("/api/auth/login", json={"token": "a" * 32})
        assert result.status_code == 429 and result.headers["retry-after"] == "900"
        assert "unknown-secret" not in str(runtime.db.rows("SELECT * FROM browser_login_attempts"))
        runtime.db.execute("UPDATE browser_login_attempts SET attempted=0")
        assert (await client.post("/api/auth/login", json={"token": "a" * 32})).status_code == 200


async def test_frontend_credential_protects_cookie_requests_and_preserves_terminal_tokens(runtime):
    runtime.settings.frontend_secret = SecretStr("private-service-secret-" + "s" * 32)
    async with browser(runtime) as client:
        assert (await client.post("/api/auth/login", json={"token": "a" * 32})).status_code == 403
        client.headers["X-Theos-Frontend-Secret"] = (
            runtime.settings.frontend_secret.get_secret_value()
        )
        assert (await client.post("/api/auth/login", json={"token": "a" * 32})).status_code == 200
        assert (await client.get("/api/me")).status_code == 200
        del client.headers["X-Theos-Frontend-Secret"]
        assert (await client.get("/api/me")).status_code == 403
        assert (
            await client.get("/api/me", headers={"Authorization": "Bearer " + "a" * 32})
        ).status_code == 200


async def test_trusted_frontend_client_addresses_have_separate_login_limits(runtime):
    runtime.settings.frontend_secret = SecretStr("private-service-secret-" + "s" * 32)
    async with browser(runtime) as client:
        client.headers["X-Theos-Frontend-Secret"] = (
            runtime.settings.frontend_secret.get_secret_value()
        )
        client.headers["X-Theos-Client-IP"] = "203.0.113.10"
        for _ in range(20):
            assert (
                await client.post("/api/auth/login", json={"token": "invalid"})
            ).status_code == 401
        assert (await client.post("/api/auth/login", json={"token": "a" * 32})).status_code == 429
        client.headers["X-Theos-Client-IP"] = "203.0.113.11"
        assert (await client.post("/api/auth/login", json={"token": "a" * 32})).status_code == 200
