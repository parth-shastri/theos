"""Browser account consent, tool access, and owner/conversation boundaries."""

import asyncio
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.shared.auth import OAuthToken
from pydantic import SecretStr, ValidationError

from harness import AssistantMessage, ToolCall
from theos.server import create_app
from theos.services.google.oauth import SCOPES, OAuth
from theos.services.zepto.auth import ZeptoTokenStorage
from theos.settings import Settings

from .test_oauth_gmail_health import configure


def browser(runtime, owner="alice"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        base_url="http://test",
        headers={"Authorization": "Bearer " + ("a" if owner == "alice" else "b") * 32},
    )


@pytest.mark.parametrize("owner", ["telegram:123", "telegram-group:1:0:123", "terminal:local", ""])
def test_browser_ids_cannot_overlap_other_transports(owner):
    with pytest.raises(ValidationError, match="namespaces"):
        Settings(_env_file=None, users={owner: "a" * 32})


async def test_disabled_connections_and_status_do_not_expose_configuration(runtime):
    async with browser(runtime) as client:
        client.headers.clear()
        assert (await client.get("/api/connections")).status_code == 401
        assert (await client.post("/api/connections/gmail/connect")).status_code == 401
        client.headers["Authorization"] = "Bearer " + "a" * 32
        data = (await client.get("/api/connections")).json()
        assert not any(account["configured"] for account in data["accounts"])
        assert (await client.post("/api/connections/gmail/connect")).status_code == 502
        assert (await client.post("/api/connections/unknown/connect")).status_code == 400
        assert (await client.post("/api/connections/unknown/disconnect")).status_code == 400
        assert (
            await client.post("/api/connections/zepto/finish", json={"url": "x" * 4001})
        ).status_code == 422
        assert runtime.db.rows("SELECT * FROM oauth_states") == []


@pytest.mark.parametrize("service", ["gmail", "health"])
async def test_google_browser_consent_binds_owner_and_survives_restart(runtime, service):
    configure(runtime.settings)
    seen = []

    def endpoint(request):
        seen.append(request)
        if request.url.path.endswith("/revoke"):
            return httpx.Response(503)
        form = parse_qs(request.content.decode())
        assert form["code_verifier"] and form["redirect_uri"]
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "scope": " ".join(SCOPES[service]),
                "expires_in": 3600,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as remote:
        runtime.oauth = OAuth(runtime.settings, runtime.db, remote)
        async with browser(runtime) as alice, browser(runtime, "bob") as bob:
            started = (
                await alice.post(f"/api/connections/{service}/connect", json={"owner": "bob"})
            ).json()
            query = parse_qs(urlsplit(started["url"]).query)
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]
            # A separate browser token at the callback cannot change the saved OAuth owner.
            callback = await bob.get(
                f"/oauth/{service}/callback", params={"state": state, "code": "one-time-code"}
            )
            assert callback.status_code == 200 and "Return to the workspace" in callback.text
            assert (
                await alice.get(
                    f"/oauth/{service}/callback", params={"state": state, "code": "code"}
                )
            ).status_code == 400
            credentials = runtime.db.rows("SELECT * FROM credentials")
            assert len(credentials) == 1 and credentials[0]["owner"] == "alice"
            assert "access-secret" not in credentials[0]["encrypted"]
            assert "refresh-secret" not in credentials[0]["encrypted"]
            restored = OAuth(runtime.settings, runtime.db, remote)
            assert await restored.access_token("alice", service) == "access-secret"
            alice_status = (await alice.get("/api/connections")).json()
            bob_status = (await bob.get("/api/connections")).json()
            assert next(a for a in alice_status["accounts"] if a["id"] == service)["connected"]
            assert not any(a["connected"] for a in bob_status["accounts"])
            assert "secret" not in json.dumps(alice_status)
            assert runtime.db.rows("SELECT * FROM sessions") == []
            await bob.post(f"/api/connections/{service}/disconnect")
            assert runtime.db.one("SELECT * FROM credentials WHERE owner='alice'")
            result = await alice.post(f"/api/connections/{service}/disconnect")
            assert result.json() == {"disconnected": True, "revoked_at_google": False}
            assert not runtime.db.rows("SELECT * FROM credentials")


async def test_google_browser_setup_cancellation_expiry_and_revoked_access(runtime):
    configure(runtime.settings)
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    async with browser(runtime) as client:

        async def start():
            link = (await client.post("/api/connections/gmail/connect")).json()["url"]
            return parse_qs(urlsplit(link).query)["state"][0]

        old_state, new_state = await start(), await start()
        assert (
            await client.get("/oauth/gmail/callback", params={"state": old_state, "code": "code"})
        ).status_code == 400
        await client.post("/api/connections/gmail/disconnect")
        assert (
            await client.get("/oauth/gmail/callback", params={"state": new_state, "code": "code"})
        ).status_code == 400
        expired = await start()
        runtime.db.execute("UPDATE oauth_states SET expires=0")
        assert (
            await client.get("/oauth/gmail/callback", params={"state": expired, "code": "code"})
        ).status_code == 400
        revoked = await start()
        runtime.settings.users.pop("alice")
        assert (
            await client.get("/oauth/gmail/callback", params={"state": revoked, "code": "code"})
        ).status_code == 403
        assert not runtime.db.rows("SELECT * FROM credentials")


async def test_browser_tools_include_configured_accounts_and_sandbox(runtime):
    configure(runtime.settings)
    runtime.settings.sandbox.enabled = True
    async with browser(runtime) as client:
        session = (await client.post("/api/sessions", json={})).json()
        tools = (await client.get(f"/api/sessions/{session['id']}/tools")).json()
        by_name = {tool["name"]: tool for tool in tools}
        assert {"gmail_connect", "get_health_summary", "run_command"} <= by_name.keys()
        assert by_name["gmail_send_draft"]["requires_approval"]
        assert not by_name["run_command"]["requires_approval"]
        assert not by_name["get_health_summary"]["requires_approval"]
        for tool in tools:
            assert "owner" not in tool["parameters"].get("properties", {})
        status = (await client.get("/api/connections")).json()
        assert next(s for s in status["services"] if s["id"] == "sandbox")["configured"]
    for channel in ("terminal", "telegram-group"):
        session = runtime.db.create_session("alice", "test", "default", channel=channel)
        names = {tool.name for tool in await runtime.tools(session)}
        assert not {"gmail_connect", "get_health_summary"} & names


async def test_browser_sandbox_runs_without_approval_and_keeps_owner_scope(
    runtime, scripted_models, monkeypatch
):
    runtime.settings.sandbox.enabled = True
    executed = []

    async def get(owner, session_id):
        async def run(command, opts):
            executed.append((owner, session_id, command))
            return SimpleNamespace(model_dump=lambda **kwargs: {"output": "4"})

        return SimpleNamespace(commands=SimpleNamespace(run=run))

    monkeypatch.setattr(runtime.sandboxes, "get", get)

    async def workspace_noop(*args):
        pass

    monkeypatch.setattr(runtime.workspaces, "prepare", workspace_noop)
    monkeypatch.setattr(runtime.workspaces, "save", workspace_noop)
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("code", "run_command", {"command": "echo 4"})]
            ),
            AssistantMessage("Done."),
        ]
    )
    async with browser(runtime) as alice, browser(runtime, "bob") as bob:
        session = (await alice.post("/api/sessions", json={})).json()["id"]
        other = (await alice.post("/api/sessions", json={})).json()["id"]
        assert (
            await bob.post(f"/api/sessions/{session}/turn", json={"text": "Run"})
        ).status_code == 404
        assert not executed
        response = await alice.post(
            f"/api/sessions/{session}/turn", json={"text": "Run the command"}
        )
        assert response.status_code == 200
        assert not (await alice.get(f"/api/sessions/{session}")).json()["approvals"]
        assert executed == [("alice", session, "echo 4")]
        assert other != session


async def test_zepto_browser_handoff_status_and_tools_are_owner_bound(runtime, monkeypatch):
    configure(runtime.settings)
    runtime.settings.zepto_url = "https://shopping.test/mcp"

    async def connect(flow):
        flow.state = "expected-state"
        runtime.zepto.pending_by_state[flow.state] = flow
        await flow.send_link("https://shopping.test/authorize?state=expected-state")
        try:
            code, state = await flow.callback
            assert code == "one-time-code" and state == "expected-state"
            await ZeptoTokenStorage(runtime.settings, runtime.db, flow.owner).set_tokens(
                OAuthToken(access_token="zepto-secret", token_type="Bearer")
            )
            await flow.send_status("Zepto is connected.")
        finally:
            runtime.zepto.pending.pop(flow.owner, None)
            runtime.zepto.pending_by_state.pop(flow.state, None)

    async def remote(owner, name=None, arguments=None):
        assert owner == "alice"
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="search", description="Search products", inputSchema={"type": "object"}
                )
            ]
        )

    monkeypatch.setattr(runtime.zepto, "_connect", connect)
    monkeypatch.setattr(runtime.zepto, "_remote", remote)
    async with browser(runtime) as alice, browser(runtime, "bob") as bob:
        assert (await alice.post("/api/connections/zepto/connect")).status_code == 200
        await asyncio.sleep(0)
        data = (await alice.get("/api/connections")).json()
        zepto = next(a for a in data["accounts"] if a["id"] == "zepto")
        assert zepto["setup"]["manual_return"] and "url" in zepto["setup"]
        assert "url" not in json.dumps((await bob.get("/api/connections")).json())
        url = "http://localhost/callback?code=one-time-code&state=expected-state"
        assert (
            await bob.post("/api/connections/zepto/finish", json={"url": url})
        ).status_code == 400
        assert (
            await alice.post(
                "/api/connections/zepto/finish",
                json={"url": url.replace("expected-state", "wrong-state")},
            )
        ).status_code == 400
        assert (
            await alice.post("/api/connections/zepto/finish", json={"url": url})
        ).status_code == 200
        await asyncio.sleep(0)
        assert runtime.zepto.connected("alice") and not runtime.zepto.connected("bob")
        assert "one-time-code" not in json.dumps(runtime.db.rows("SELECT * FROM sessions"))
        assert (
            await alice.post("/api/connections/zepto/finish", json={"url": url})
        ).status_code == 400
        session = (await alice.post("/api/sessions", json={})).json()["id"]
        tools = (await alice.get(f"/api/sessions/{session}/tools")).json()
        assert not next(t for t in tools if t["name"] == "zepto_search")["requires_approval"]
        await bob.post("/api/connections/zepto/disconnect")
        assert runtime.zepto.connected("alice")
        await alice.post("/api/connections/zepto/disconnect")
        assert not runtime.zepto.connected("alice")
        assert runtime.zepto.connection_status("alice") == {"status": "idle"}


async def test_zepto_pending_browser_setup_can_be_cancelled(runtime, monkeypatch):
    configure(runtime.settings)
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    cancelled = []

    async def connect(flow):
        flow.state = "cancel-state"
        runtime.zepto.pending_by_state[flow.state] = flow
        await flow.send_link("https://shopping.test/authorize?state=cancel-state")
        try:
            await flow.callback
        finally:
            cancelled.append(flow.owner)
            runtime.zepto.pending.pop(flow.owner, None)
            runtime.zepto.pending_by_state.pop(flow.state, None)

    monkeypatch.setattr(runtime.zepto, "_connect", connect)
    async with browser(runtime) as client:
        await client.post("/api/connections/zepto/connect")
        await asyncio.sleep(0)
        await client.post("/api/connections/zepto/disconnect")
        assert cancelled == ["alice"]
        assert not runtime.zepto.pending and not runtime.zepto.pending_by_state
        assert runtime.zepto.connection_status("alice") == {"status": "idle"}
        assert not runtime.db.rows("SELECT * FROM credentials")


async def test_zepto_https_callback_rechecks_access_expiry_and_replay(runtime):
    from theos.services.zepto.auth import PendingConnection

    configure(runtime.settings)
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    runtime.settings.zepto_redirect_uri = "https://assistant.test/oauth/zepto/callback"
    flow = PendingConnection(
        owner="alice",
        redirect_uri=runtime.settings.zepto_redirect_uri,
        callback=asyncio.get_running_loop().create_future(),
        send_link=None,
        send_status=None,
        created=time.time(),
        state="direct-state",
    )
    runtime.zepto.pending[flow.owner] = flow
    runtime.zepto.pending_by_state[flow.state] = flow
    async with browser(runtime) as client:
        runtime.settings.users.pop("alice")
        params = {"state": flow.state, "code": "code"}
        assert (await client.get("/oauth/zepto/callback", params=params)).status_code == 403
        assert not flow.callback.done()
        runtime.settings.users["alice"] = SecretStr("a" * 32)
        flow.created -= 601
        assert (await client.get("/oauth/zepto/callback", params=params)).status_code == 400
        flow.created += 601
        assert (await client.get("/oauth/zepto/callback", params=params)).status_code == 200
        assert await flow.callback == ("code", "direct-state")
        assert (await client.get("/oauth/zepto/callback", params=params)).status_code == 400


async def test_zepto_failed_setup_preserves_existing_credentials_and_reports_failure(
    runtime, monkeypatch
):
    configure(runtime.settings)
    runtime.settings.zepto_url = "https://shopping.test/mcp"
    await ZeptoTokenStorage(runtime.settings, runtime.db, "alice").set_tokens(
        OAuthToken(access_token="existing-secret", token_type="Bearer")
    )

    async def fail():
        raise RuntimeError("Provider unavailable")

    monkeypatch.setattr(runtime.zepto, "_ensure_client_info", fail)
    await runtime.zepto.connect_from_browser("alice")
    await runtime.zepto.pending["alice"].task
    status = runtime.zepto.connection_status("alice")
    assert status["status"] == "failed" and "url" not in status
    assert runtime.zepto.connected("alice")
    assert not runtime.zepto.pending


async def test_health_browser_disconnection_cancels_only_owner_jobs(runtime):
    configure(runtime.settings)
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    for owner in ("alice", "bob"):
        runtime.oauth.save(owner, "health", {"access_token": "a", "refresh_token": "r"})
        runtime.db.execute(
            "INSERT INTO jobs(id,owner,kind,payload,due,updated) VALUES (?,?,'nutrition','{}',0,0)",
            (owner + "-job", owner),
        )
    async with browser(runtime) as client:
        await client.post("/api/connections/health/disconnect")
        jobs = {row["owner"]: row["status"] for row in runtime.db.rows("SELECT * FROM jobs")}
        assert jobs == {"alice": "cancelled", "bob": "pending"}
        assert runtime.db.one("SELECT * FROM credentials WHERE owner='bob'")
