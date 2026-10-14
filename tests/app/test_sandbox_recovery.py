"""Fixed creation expiry, stale cached clients, and safe remote recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from opensandbox import Sandbox
from opensandbox.exceptions import SandboxApiException

from theos.services.errors import ServiceError
from theos.services.sandbox.client import Sandboxes

from .conftest import call_tool


@pytest.fixture
def boxes(runtime, monkeypatch):
    created, now = [], [datetime.now(UTC)]

    class Clock:
        @staticmethod
        def now(zone):
            return now[0]

        fromisoformat = datetime.fromisoformat

    monkeypatch.setattr("theos.services.sandbox.client.datetime", Clock)

    class Box:
        def __init__(self, lifetime):
            self.id = str(len(created))
            self.created = now[0]
            self.expiry = now[0] + lifetime
            self.dead, self.error, self.kills, self.renewals = False, None, 0, 0

        async def get_info(self):
            if self.error:
                raise self.error
            if self.dead:
                raise SandboxApiException(status_code=404)
            return SimpleNamespace(
                created_at=self.created,
                expires_at=self.expiry,
                status=SimpleNamespace(state="Running"),
                model_dump=lambda **kw: {"id": self.id, "expires_at": self.expiry.isoformat()},
            )

        async def close(self):
            pass

        async def kill(self):
            self.dead = True
            self.kills += 1

        async def renew(self, value):
            self.renewals += 1

    async def create(*args, **kwargs):
        box = Box(kwargs["timeout"])
        created.append(box)
        await asyncio.sleep(0)
        return box

    async def connect(identifier, **kwargs):
        box = next(box for box in created if box.id == identifier)
        await box.get_info()
        return box

    monkeypatch.setattr(Sandbox, "create", create)
    monkeypatch.setattr(Sandbox, "connect", connect)
    return created, now


async def test_one_hour_is_fixed_from_creation_and_renew_cannot_extend_it(runtime, boxes):
    created, now = boxes
    first = await runtime.sandboxes.get("alice", "chat")
    original = runtime.db.record("alice", "sandbox", "chat")
    assert first.expiry - first.created == timedelta(hours=1)
    now[0] += timedelta(minutes=30)
    result = await call_tool(
        runtime.sandboxes.tools("alice", "chat"), "sandbox_lifecycle", action="renew"
    )
    assert result["renewed"] is False and first.renewals == 0
    assert runtime.db.record("alice", "sandbox", "chat") == original
    now[0] += timedelta(minutes=31)
    second = await runtime.sandboxes.get("alice", "chat")
    assert second.id != first.id and first.kills == 1 and len(created) == 2


async def test_expired_cached_client_is_replaced_without_explicit_forget(runtime, boxes):
    created, _ = boxes
    first = await runtime.sandboxes.get("alice", "chat")
    first.dead = True
    replacements = await asyncio.gather(*(runtime.sandboxes.get("alice", "chat") for _ in range(4)))
    assert len(created) == 2 and all(box is created[1] for box in replacements)
    assert runtime.db.record("alice", "sandbox", "chat")["sandbox_id"] == created[1].id


async def test_reconnection_keeps_the_original_creation_deadline(runtime, boxes):
    _, now = boxes
    first = await runtime.sandboxes.get("alice", "chat")
    original = runtime.db.record("alice", "sandbox", "chat")
    await runtime.sandboxes.close()
    now[0] += timedelta(minutes=40)
    restored = Sandboxes(runtime.settings, runtime.db, runtime.files)
    assert (await restored.get("alice", "chat")).id == first.id
    assert runtime.db.record("alice", "sandbox", "chat") == original
    await restored.close()


async def test_transient_cached_error_preserves_reference_and_never_creates_replacement(
    runtime, boxes
):
    created, _ = boxes
    first = await runtime.sandboxes.get("alice", "chat")
    original = runtime.db.record("alice", "sandbox", "chat")
    first.error = SandboxApiException(status_code=503)
    with pytest.raises(ServiceError):
        await runtime.sandboxes.get("alice", "chat")
    assert len(created) == 1 and runtime.db.record("alice", "sandbox", "chat") == original
    first.error = None


async def test_destroy_without_an_instance_does_not_create_one_and_restart_replaces_it(
    runtime, boxes
):
    created, _ = boxes
    await call_tool(runtime.sandboxes.tools("alice", "chat"), "sandbox_lifecycle", action="destroy")
    assert not created
    first = await runtime.sandboxes.get("alice", "chat")
    result = await call_tool(
        runtime.sandboxes.tools("alice", "chat"), "sandbox_lifecycle", action="restart"
    )
    assert result["id"] != first.id and first.kills == 1
