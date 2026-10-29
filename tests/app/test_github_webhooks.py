"""Signed GitHub events remain private, durable, and independent of model turns."""

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from theos.services.github import create_account
from theos.services.github.events import attention
from theos.services.github.notifications import GitHubNotifications
from theos.settings import Settings

from .test_browser_connections import browser


@pytest.fixture
async def events(runtime):
    runtime.settings.github_webhook_secret = SecretStr("webhook-secret-" + "s" * 40)
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    runtime.settings.telegram_token = SecretStr("test-bot-token")
    runtime.settings.telegram_users.add(123)
    kind = type(runtime.settings.github)
    runtime.settings.github = kind(
        client_id="client",
        client_secret="secret",
        redirect_uri="http://localhost:8080/oauth/github/callback",
    )
    runtime.github = create_account(runtime.settings, runtime.db, runtime.http)
    identities = {
        "alice-token": {"id": 101, "login": "alice"},
        "bob-token": {"id": 202, "login": "bob"},
        "telegram-token": {"id": 303, "login": "neuron"},
    }
    state = {"denied": {"bob-token"}, "offline": False, "identities": identities}

    def remote(request):
        assert request.method == "GET" and request.url.host == "api.github.com"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        token = request.headers["authorization"].removeprefix("Bearer ")
        if state["offline"]:
            return httpx.Response(503)
        if request.url.path == "/user":
            return httpx.Response(200, json=identities[token])
        assert request.url.path == "/repositories/71"
        return httpx.Response(404 if token in state["denied"] else 200, json={"id": 71})

    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as http:
        runtime.github_events = GitHubNotifications(
            runtime.settings, runtime.db, http, runtime.github
        )
        for owner, token in [
            ("alice", "alice-token"),
            ("bob", "bob-token"),
            ("telegram:123", "telegram-token"),
        ]:
            runtime.github.save(owner, {"access_token": token, "expires_at": time.time() + 3600})
        yield runtime.github_events, state


def payload(body="@alice @bob @neuron please review"):
    return {
        "action": "opened",
        "repository": {"id": 71, "full_name": "sample/project"},
        "sender": {"id": 999},
        "issue": {"number": 12, "title": "Fix café <script>", "body": body},
        "owner": "bob",
    }


def signed(events, data, event="issues", delivery="delivery-one"):
    raw = json.dumps(data, ensure_ascii=False).encode()
    signature = (
        "sha256="
        + hmac.new(
            events.settings.github_webhook_secret.get_secret_value().encode(), raw, hashlib.sha256
        ).hexdigest()
    )
    return raw, {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": delivery,
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


def receive(events, data, event="issues", delivery="delivery-one"):
    raw, headers = signed(events, data, event, delivery)
    return events.receive(raw, headers["X-Hub-Signature-256"], delivery, event)


async def test_public_receiver_verifies_raw_bytes_before_persistence(runtime, events):
    service, _ = events
    await service.configure("alice", True)
    raw, headers = signed(service, payload())
    async with browser(runtime) as client:
        client.headers.clear()
        assert (await client.post("/webhooks/github", content=raw)).status_code == 403
        assert (
            await client.post("/webhooks/github", content=raw + b" ", headers=headers)
        ).status_code == 403
        assert not runtime.db.rows("SELECT * FROM github_deliveries")
        result = await client.post("/webhooks/github", content=raw, headers=headers)
        assert result.status_code == 202 and not result.json()["duplicate"]
        row = runtime.db.one("SELECT * FROM github_deliveries")
        assert "café" not in row["encrypted"] and "alice" not in row["encrypted"]
        assert service.account.cipher.decrypt(row["encrypted"].encode()) == raw
        assert (await client.post("/webhooks/github", content=raw, headers=headers)).json()[
            "duplicate"
        ]
        changed, changed_headers = signed(service, payload("different"))
        assert (
            await client.post("/webhooks/github", content=changed, headers=changed_headers)
        ).status_code == 400
        assert len(runtime.db.rows("SELECT * FROM github_deliveries")) == 1
        assert (
            await client.post("/webhooks/github", content=b"x" * (1024 * 1024 + 1))
        ).status_code == 413
        invalid, invalid_headers = signed(service, {"repository": []})
        assert (
            await client.post("/webhooks/github", content=invalid, headers=invalid_headers)
        ).status_code == 400


async def test_owner_routing_access_checks_inbox_and_duplicate_delivery(runtime, events):
    service, _ = events
    for owner in ("alice", "bob"):
        await service.configure(owner, True)
    receive(service, payload())
    assert not service.inbox("alice")  # Receipt does not expose an unverified event.
    await service.tick()
    await service.tick()
    notices = service.inbox("alice")
    assert len(notices) == 1 and not service.inbox("bob")
    assert notices[0]["url"] == "https://github.com/sample/project/issues/12"
    assert receive(service, payload())["duplicate"]
    await service.tick()
    assert len(service.inbox("alice")) == 1
    assert runtime.db.one("SELECT encrypted FROM github_deliveries")["encrypted"] is None
    async with browser(runtime) as alice, browser(runtime, "bob") as bob:
        visible = (await alice.get("/api/notifications")).json()
        assert visible[0]["source"] == "github"
        assert (await bob.get("/api/notifications")).json() == []
        path = f"/api/connections/github/notifications/{notices[0]['id']}/read"
        assert (await bob.post(path)).status_code == 404
        assert (await alice.post(path)).json() == {"read": True}
        assert (await alice.get("/api/notifications")).json() == []
        assert (
            await alice.put(
                "/api/connections/github/notifications", json={"enabled": True, "telegram": True}
            )
        ).status_code == 403
    assert not runtime.db.rows("SELECT * FROM tool_runs")
    assert not runtime.db.rows("SELECT * FROM sessions")


async def test_opt_in_cancel_reconnect_and_current_identity_do_not_replay_old_events(
    runtime, events
):
    service, state = events
    receive(service, payload(), delivery="before-opt-in")
    await service.configure("alice", True)
    await service.tick()
    assert not service.inbox("alice")
    receive(service, payload(), delivery="new-event")
    state["identities"]["alice-token"] = {"id": 987, "login": "someone-else"}
    await service.tick()
    assert not service.inbox("alice") and not service.status("alice")["enabled"]
    state["identities"]["alice-token"] = {"id": 101, "login": "alice"}
    await service.configure("alice", True)
    receive(service, payload(), delivery="cancel-event")
    service.disable("alice")
    await service.tick()
    assert not service.inbox("alice")
    # Disconnecting the account also disables queued alerts through the public API.
    await service.configure("alice", True)
    async with browser(runtime) as client:
        assert (await client.post("/api/connections/github/disconnect")).status_code == 200
    assert not service.subscription("alice")["enabled"]


async def test_background_retry_and_restart_preserve_one_inbox_item(runtime, events):
    service, state = events
    await service.configure("alice", True)
    receive(service, payload())
    state["offline"] = True
    await service.tick()
    row = runtime.db.one("SELECT * FROM github_deliveries")
    assert row["status"] == "pending" and row["attempts"] == 1 and not service.inbox("alice")
    runtime.db.execute("UPDATE github_deliveries SET due=0")
    state["offline"] = False
    restarted = GitHubNotifications(runtime.settings, runtime.db, service.http, runtime.github)
    await restarted.tick()
    await restarted.tick()
    assert len(service.inbox("alice")) == 1


async def test_telegram_is_private_rechecks_access_and_never_retries_uncertain_send(
    runtime, events
):
    service, state = events
    await service.configure("telegram:123", True, True)
    receive(service, payload())
    telegram = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("lost response")))
    await service.tick(telegram)
    assert telegram.send.await_count == 1
    args = telegram.send.await_args.args
    assert args[0] == 123 and "sample/project" in args[1]
    assert service.inbox("telegram:123")[0]["telegram"] == "uncertain"
    await service.tick(telegram)
    assert telegram.send.await_count == 1
    receive(service, payload(), delivery="revoked-access")
    await service.tick()
    state["denied"].add("telegram-token")
    await service.deliver(telegram)
    assert telegram.send.await_count == 1
    assert service.inbox("telegram:123")[0]["telegram"] == "blocked"
    # An abrupt process loss during a send remains uncertain on database recovery.
    runtime.db.execute("UPDATE github_notifications SET telegram='sending'")
    runtime.db.recover()
    assert all(row["telegram"] == "uncertain" for row in service.inbox("telegram:123"))
    await service.deliver(telegram)
    assert telegram.send.await_count == 1


async def test_notification_controls_are_authenticated_and_telegram_commands_use_no_model(
    runtime, events
):
    from theos.transports.telegram.connections import handle

    service, _ = events
    async with browser(runtime) as client:
        client.headers.clear()
        assert (
            await client.put("/api/connections/github/notifications", json={"enabled": True})
        ).status_code == 401
    bot = SimpleNamespace(
        runtime=runtime, settings=runtime.settings, db=runtime.db, send=AsyncMock()
    )
    assert await handle(
        bot,
        {"text": "/github_notifications on"},
        "telegram:123",
        "telegram-private",
        123,
        None,
        None,
    )
    assert service.status("telegram:123")["telegram"]
    assert await handle(
        bot,
        {"text": "/github_notifications off"},
        "telegram:123",
        "telegram-private",
        123,
        None,
        None,
    )
    assert not service.status("telegram:123")["enabled"]
    assert not runtime.db.rows("SELECT * FROM sessions")


@pytest.mark.parametrize(
    ("event", "data", "expected"),
    [
        ("issues", dict(payload(), action="assigned", assignee={"id": 101}), "Assigned"),
        (
            "pull_request",
            {
                "action": "review_requested",
                "repository": {"full_name": "sample/project"},
                "pull_request": {"number": 5, "title": "Update"},
                "requested_reviewer": {"id": 101},
            },
            "Review requested",
        ),
        (
            "issue_comment",
            dict(payload(), action="created", comment={"body": "Hello @alice"}),
            "mentioned",
        ),
        (
            "workflow_run",
            {
                "action": "completed",
                "repository": {"full_name": "sample/project"},
                "workflow_run": {
                    "id": 55,
                    "name": "CI",
                    "conclusion": "failure",
                    "actor": {"id": 101},
                },
            },
            "Workflow failed",
        ),
        (
            "issue_comment",
            dict(payload(), action="created", comment={"body": "Hello @alice-other"}),
            None,
        ),
        ("issues", dict(payload(), sender={"id": 101}), None),
        (
            "issues",
            dict(
                payload(), action="edited", changes={"body": {"from": "@alice already mentioned"}}
            ),
            None,
        ),
        (
            "workflow_run",
            {
                "action": "completed",
                "repository": {"full_name": "sample/project"},
                "workflow_run": {"id": 55, "conclusion": "success", "actor": {"id": 101}},
            },
            None,
        ),
    ],
)
def test_only_selected_attention_events_generate_canonical_links(event, data, expected):
    result = attention(event, data, 101, "alice")
    if expected:
        assert expected in result[0] and result[1].startswith("https://github.com/sample/project/")
    else:
        assert result is None


def test_webhook_configuration_requires_strong_secret_and_encryption():
    with pytest.raises(ValueError, match="32 characters"):
        Settings(_env_file=None, github_webhook_secret="weak")
    with pytest.raises(ValueError, match="encryption key"):
        Settings(_env_file=None, github_webhook_secret="s" * 48)


async def test_retention_runs_even_after_webhooks_are_disabled(runtime, events):
    service, _ = events
    await service.configure("alice", True)
    receive(service, payload(), delivery="expired-content")
    receive(service, payload(), delivery="expired-delivery")
    runtime.db.execute(
        "UPDATE github_deliveries SET created=? WHERE id='expired-content'",
        (time.time() - 8 * 86400,),
    )
    runtime.db.execute(
        "UPDATE github_deliveries SET created=? WHERE id='expired-delivery'",
        (time.time() - 31 * 86400,),
    )
    runtime.settings.github_webhook_secret = SecretStr("")
    await service.tick()
    old = runtime.db.one("SELECT * FROM github_deliveries WHERE id='expired-content'")
    assert old["status"] == "expired" and old["encrypted"] is None
    assert runtime.db.one("SELECT 1 FROM github_deliveries WHERE id='expired-delivery'") is None
