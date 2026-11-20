"""Check private admission, deduplication, cleanup, and crash recovery without Telegram."""

import asyncio
import time

import httpx
import pytest

from theos_calling.server import MAX_AUDIO, create_app
from theos_calling.settings import Settings


class Caller:
    def __init__(self):
        self.started = False
        self.closed = False
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.error = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    async def play(self, recipient, path):
        self.calls.append((recipient, path, path.read_bytes()))
        assert path.stat().st_mode & 0o777 == 0o600
        self.entered.set()
        await self.release.wait()
        if self.error:
            raise TimeoutError("unknown outcome")


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        api_id=12345,
        api_hash="a" * 32,
        key="k" * 32,
        recipients={123456789},
        data_dir=tmp_path / "calling",
    )


@pytest.fixture
def auth():
    return {"Authorization": "Bearer " + "k" * 32, "Content-Type": "audio/mpeg"}


def params():
    return {"recipient": 123456789, "expires": time.time() + 120}


async def test_one_call_and_private_cleanup(settings, auth):
    caller = Caller()
    app = create_app(settings, caller=caller)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            response = await c.post(
                "/v1/calls/reminder:1", headers=auth, params=params(), content=b"mp3"
            )
            assert response.status_code == 202
            assert response.json() == {"id": "reminder:1", "status": "accepted"}
            await asyncio.wait_for(caller.entered.wait(), 1)
            duplicate = await c.post(
                "/v1/calls/reminder:1", headers=auth, params=params(), content=b"mp3"
            )
            assert duplicate.status_code == 202
            assert len(caller.calls) == 1
            busy = await c.post("/v1/calls/other", headers=auth, params=params(), content=b"mp3")
            assert busy.status_code == 409
            changed = await c.post(
                "/v1/calls/reminder:1", headers=auth, params=params(), content=b"other"
            )
            assert changed.status_code == 409
            caller.release.set()
            await app.state.task
            assert (await c.get("/v1/calls/reminder:1", headers=auth)).json()[
                "status"
            ] == "completed"
            assert not caller.calls[0][1].exists()
            assert not list(settings.data_dir.glob("clip-*.mp3"))
            repeated = await c.post(
                "/v1/calls/reminder:1", headers=auth, params=params(), content=b"mp3"
            )
            assert repeated.json()["status"] == "completed"
            assert len(caller.calls) == 1
    assert caller.closed


@pytest.mark.parametrize(
    "case,status",
    [
        ("auth", 401),
        ("recipient", 403),
        ("expired", 410),
        ("future", 410),
        ("nan", 410),
        ("type", 415),
        ("empty", 400),
        ("oversized", 413),
        ("id", 422),
    ],
)
async def test_rejected_requests_never_call(settings, auth, case, status):
    caller = Caller()
    app = create_app(settings, caller=caller)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            args = {"headers": auth, "params": params(), "content": b"mp3"}
            url = "/v1/calls/test"
            if case == "auth":
                args["headers"] = {"Content-Type": "audio/mpeg"}
            elif case == "recipient":
                args["params"]["recipient"] = 2
            elif case == "expired":
                args["params"]["expires"] = time.time() - 1
            elif case == "future":
                args["params"]["expires"] = time.time() + 1000
            elif case == "nan":
                args["params"]["expires"] = "nan"
            elif case == "type":
                args["headers"] = {**auth, "Content-Type": "text/plain"}
            elif case == "empty":
                args["content"] = b""
            elif case == "oversized":
                args["content"] = b"x" * (MAX_AUDIO + 1)
            elif case == "id":
                url = "/v1/calls/bad%20id"
            assert (await c.post(url, **args)).status_code == status
            assert not caller.calls
            assert app.state.db.execute("SELECT count(*) FROM calls").fetchone()[0] == 0


async def test_restart_preserves_unknown_call_and_removes_orphan_audio(settings, auth):
    first = Caller()
    app = create_app(settings, caller=first)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            await c.post("/v1/calls/interrupted", headers=auth, params=params(), content=b"mp3")
            await asyncio.wait_for(first.entered.wait(), 1)
    assert not first.calls[0][1].exists()
    (settings.data_dir / "clip-orphan.mp3").write_bytes(b"old audio")
    second = Caller()
    app = create_app(settings, caller=second)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            repeated = await c.post(
                "/v1/calls/interrupted", headers=auth, params=params(), content=b"mp3"
            )
            assert repeated.json()["status"] == "uncertain"
            assert not second.calls
            assert not list(settings.data_dir.glob("clip-*.mp3"))


async def test_daily_limit_and_provider_failure(settings, auth):
    settings.daily_limit = 1
    caller = Caller()
    caller.error = True
    caller.release.set()
    app = create_app(settings, caller=caller)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            await c.post("/v1/calls/failed", headers=auth, params=params(), content=b"mp3")
            await app.state.task
            assert (await c.get("/v1/calls/failed", headers=auth)).json()["status"] == "uncertain"
            assert not list(settings.data_dir.glob("clip-*.mp3"))
            assert (
                await c.post("/v1/calls/capped", headers=auth, params=params(), content=b"mp3")
            ).status_code == 429


async def test_dynamic_recipient_requires_authenticated_private_proof(settings, auth):
    from urllib.parse import parse_qs, urlsplit

    caller = Caller()
    caller.profile_url = "https://t.me/theos_test"
    app = create_app(settings, caller=caller)
    id = "d" * 32
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post("/v1/connections/" + id, json={})).status_code == 401
            linked = await client.post(
                "/v1/connections/" + id,
                headers={"Authorization": auth["Authorization"]},
                json={"expected_recipient": 456},
            )
            assert linked.status_code == 200
            proof = parse_qs(urlsplit(linked.json()["url"]).query)["text"][0]
            args = {
                "headers": auth,
                "params": {"recipient": 456, "expires": time.time() + 120},
                "content": b"mp3",
            }
            assert (await client.post("/v1/calls/new-user", **args)).status_code == 403
            await caller.connection_handler(789, proof)
            assert (await client.post("/v1/calls/new-user", **args)).status_code == 403
            await caller.connection_handler(456, proof)
            assert (await client.get("/v1/connections/" + id, headers=auth)).json()[
                "recipient"
            ] == 456
            assert (await client.post("/v1/calls/new-user", **args)).status_code == 202
            caller.release.set()
            await app.state.task
            await client.delete("/v1/connections/" + id, headers=auth)
            assert (await client.post("/v1/calls/revoked", **args)).status_code == 403


async def test_spoken_response_and_feedback_are_authenticated_ephemeral_and_deduplicated(
    settings, auth
):
    settings.spoken_approvals = True
    caller = Caller()
    answered = []

    async def interact(recipient, path, respond):
        answered.append(recipient)
        caller.entered.set()
        feedback, end = await respond(b"RIFF-test-response")
        assert end is True
        assert feedback.read_bytes() == b"feedback-mp3"
        assert feedback.stat().st_mode & 0o777 == 0o600

    caller.interact = interact
    app = create_app(settings, caller=caller)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/calls/spoken",
                headers=auth,
                params={**params(), "interactive": True},
                content=b"prompt",
            )
            assert response.status_code == 202
            await asyncio.wait_for(caller.entered.wait(), 1)
            assert (await client.get("/v1/calls/spoken/response")).status_code == 401
            reply = await client.get("/v1/calls/spoken/response", headers=auth)
            assert (
                reply.content == b"RIFF-test-response"
                and reply.headers["cache-control"] == "no-store"
            )
            assert (await client.get("/v1/calls/other/response", headers=auth)).status_code == 410
            changed = await client.post(
                "/v1/calls/spoken", headers=auth, params=params(), content=b"prompt"
            )
            assert changed.status_code == 409
            finish = await client.post(
                "/v1/calls/spoken/finish", headers=auth, content=b"feedback-mp3"
            )
            assert finish.status_code == 200
            await app.state.task
            assert app.state.dialogue is None and not list(settings.data_dir.glob("clip-*.mp3"))
            assert (await client.get("/v1/calls/spoken/response", headers=auth)).status_code == 410
            duplicate = await client.post(
                "/v1/calls/spoken",
                headers=auth,
                params={**params(), "interactive": True},
                content=b"prompt",
            )
            assert duplicate.json()["status"] == "completed" and answered == [123456789]


async def test_spoken_capture_is_env_gated(settings, auth):
    app = create_app(settings, caller=Caller())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/calls/spoken",
                headers=auth,
                params={**params(), "interactive": True},
                content=b"prompt",
            )
            assert response.status_code == 409
            assert app.state.db.execute("SELECT count(*) FROM calls").fetchone()[0] == 0


async def test_interrupted_spoken_call_loses_audio_and_cannot_restart_the_dial(settings, auth):
    settings.spoken_approvals = True
    caller = Caller()

    async def interact(recipient, path, respond):
        caller.entered.set()
        await respond(b"private-ephemeral-response")

    caller.interact = interact
    app = create_app(settings, caller=caller)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/v1/calls/interrupted-voice",
                headers=auth,
                params={**params(), "interactive": True},
                content=b"prompt",
            )
            await asyncio.wait_for(caller.entered.wait(), 1)
            assert app.state.dialogue.response == b"private-ephemeral-response"
    assert app.state.dialogue is None
    restarted = create_app(settings, caller=Caller())
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            assert (
                await client.get("/v1/calls/interrupted-voice/response", headers=auth)
            ).status_code == 410
            duplicate = await client.post(
                "/v1/calls/interrupted-voice",
                headers=auth,
                params={**params(), "interactive": True},
                content=b"prompt",
            )
            assert duplicate.json()["status"] == "uncertain"
            assert not restarted.state.caller.calls


async def test_two_voice_turns_continue_one_call_and_reject_stale_feedback(settings, auth):
    settings.two_way = True
    caller = Caller()
    ready = [asyncio.Event(), asyncio.Event()]

    async def interact(recipient, path, respond):
        for index in range(2):
            ready[index].set()
            feedback, end = await respond(b"RIFF-utterance-" + str(index + 1).encode())
            assert feedback.read_bytes() == b"reply-" + str(index + 1).encode()
            assert end == (index == 1)

    caller.interact = interact
    app = create_app(settings, caller=caller)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/calls/conversation",
                headers=auth,
                params={**params(), "interactive": True, "dialogue_expires": time.time() + 300},
                content=b"greeting",
            )
            assert response.status_code == 202
            await ready[0].wait()
            first = await client.get("/v1/calls/conversation/response", headers=auth)
            assert first.headers["x-theos-voice-turn"] == "1"
            await client.post(
                "/v1/calls/conversation/finish",
                headers=auth,
                params={"turn": 1, "end": False},
                content=b"reply-1",
            )
            await ready[1].wait()
            second = await client.get("/v1/calls/conversation/response", headers=auth)
            assert second.headers["x-theos-voice-turn"] == "2"
            duplicate = await client.post(
                "/v1/calls/conversation/finish",
                headers=auth,
                params={"turn": 1, "end": False},
                content=b"reply-1",
            )
            assert duplicate.status_code == 200
            assert not app.state.dialogue.feedback.done()
            wrong = await client.post(
                "/v1/calls/conversation/finish",
                headers=auth,
                params={"turn": 1, "end": False},
                content=b"changed",
            )
            assert wrong.status_code == 409
            await client.post(
                "/v1/calls/conversation/finish",
                headers=auth,
                params={"turn": 2, "end": True},
                content=b"reply-2",
            )
            await app.state.task
            assert app.state.dialogue is None
