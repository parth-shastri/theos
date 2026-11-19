"""Exercise spoken yes/no through the real approval checkpoints without external writes."""

import asyncio
import io
import json
import time
import wave

import httpx
import pytest

from harness import AssistantMessage, ToolCall
from theos.runtime import Runtime
from theos.services.custom_tables.tools import custom_tools
from theos.services.spoken_approvals import decision, spoken_prompt

from .conftest import call_tool, collect
from .test_phone_calls import telegram_call_settings as telegram_call_settings


def wav():
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(48000)
        target.writeframes(b"\x00\x04" * 24000)
    return out.getvalue()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("yes", True),
        ("Yes, approve it.", True),
        ("NO!", False),
        ("no, don't do it", False),
        ("yes no", None),
        ("maybe yes", None),
        ("yes?", None),
        ("approve unless it changed", None),
        ("", None),
        ("do not approve", False),
    ],
)
def test_only_explicit_unambiguous_decisions_are_accepted(text, expected):
    assert decision(text) is expected


@pytest.fixture
async def spoken(telegram_call_settings, db, scripted_models):
    settings = telegram_call_settings
    settings.telegram_calls.spoken_approvals = True
    settings.transcription_url = "http://transcription.test/v1"
    state = {
        "text": "yes",
        "dialed": [],
        "speech": [],
        "feedback": [],
        "responses": 0,
        "during_asr": None,
        "response_status": 200,
        "audio": wav(),
        "asr_count": 0,
    }

    async def provider(request):
        if request.url.host == "speech.example":
            state["speech"].append(json.loads(request.content)["input"])
            return httpx.Response(200, headers={"Content-Type": "audio/mpeg"}, content=b"mp3")
        if request.url.host == "transcription.test":
            state["asr_count"] += 1
            assert b"RIFF" in request.content
            if state["during_asr"]:
                state["during_asr"]()
            return httpx.Response(200, json={"text": state["text"]})
        if request.url.path.endswith("/response"):
            state["responses"] += 1
            return httpx.Response(
                state["response_status"],
                headers={"Content-Type": "audio/wav"},
                content=state["audio"],
            )
        if request.url.path.endswith("/finish"):
            state["feedback"].append(request)
            return httpx.Response(200, json={"status": "accepted"})
        state["dialed"].append(request)
        return httpx.Response(
            202, json={"id": request.url.path.rsplit("/", 1)[1], "status": "accepted"}
        )

    active = Runtime(
        settings, db, httpx.AsyncClient(transport=httpx.MockTransport(provider)), scripted_models
    )
    yield active, state
    await active.close()


async def waiting(runtime, scripted_models):
    session = runtime.db.create_session("alice", "fake", "default")
    await call_tool(
        custom_tools(runtime.db, "alice", runtime.settings.data_dir / "tables"),
        "create_custom_table",
        name="notes",
        columns={"text": "TEXT"},
    )
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("checkout", "zepto_confirm_cart", {"name": "notes"})]
            )
        ]
    )
    events = await collect(runtime.start("alice", session["id"], "Prepare the action"))
    assert events[-1]["status"] == "waiting_for_approval"
    runtime.db.execute("UPDATE phone_calls SET due=?", (time.time() - 1,))
    return session, runtime.db.one("SELECT * FROM approvals")


@pytest.mark.parametrize(
    "reply,expected", [("yes", "approved"), ("no", "denied"), ("yes no", "unrecognized")]
)
async def test_spoken_decision_resumes_one_exact_action_once(
    spoken, scripted_models, checkout_tool, reply, expected
):
    runtime, state = spoken
    session, approval = await waiting(runtime, scripted_models)
    state["text"] = reply
    await runtime.phone_calls.tick(time.time())
    assert len(state["dialed"]) == 1
    assert state["dialed"][0].url.params["interactive"] == "true"
    assert "Product: notes" in state["speech"][0]
    assert "say yes" in state["speech"][0]
    scripted_models.responses.append([AssistantMessage("The decision was handled.")])
    await runtime.spoken_approvals.tick()
    if runtime.spoken_approvals.workers:
        await asyncio.gather(*runtime.spoken_approvals.workers)
    await runtime.spoken_approvals.tick()
    result = runtime.db.one("SELECT * FROM phone_calls")
    assert result["voice_status"] == expected
    assert state["responses"] == 1
    assert len(state["dialed"]) == len(state["feedback"]) == 1
    saved = runtime.db.one("SELECT status FROM approvals")["status"]
    assert saved == (expected if expected != "unrecognized" else "pending")
    runs = runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")
    if expected in {"approved", "denied"}:
        assert len(runs) == 1
        assert runs[0]["status"] == ("completed" if expected == "approved" else "denied")
    else:
        assert not runs
    assert "RIFF" not in json.dumps(runtime.db.rows("SELECT * FROM records"))
    assert not runtime.db.rows("SELECT * FROM files")


@pytest.mark.parametrize("change", ["review", "expiry", "access", "recipient", "resolved"])
async def test_change_during_transcription_prevents_a_decision(
    spoken, scripted_models, checkout_tool, change
):
    runtime, state = spoken
    session, approval = await waiting(runtime, scripted_models)
    await runtime.phone_calls.tick(time.time())

    def mutate():
        if change == "review":
            runtime.db.execute(
                "UPDATE approvals SET preview=? WHERE id=?",
                (json.dumps({"name": "other"}), approval["id"]),
            )
        elif change == "expiry":
            runtime.db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
        elif change == "access":
            runtime.settings.users = {}
        elif change == "recipient":
            runtime.settings.telegram_calls.recipients = {"alice": 987}
        else:
            runtime.db.execute("UPDATE approvals SET status='denied'")

    state["during_asr"] = mutate
    await runtime.spoken_approvals.tick()
    assert not runtime.spoken_approvals.workers
    assert runtime.db.one("SELECT voice_status FROM phone_calls")["voice_status"] == "stale"
    assert not runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")


async def test_changed_remote_preview_cannot_use_the_spoken_grant(
    spoken, scripted_models, checkout_tool, monkeypatch
):
    runtime, state = spoken
    session, approval = await waiting(runtime, scripted_models)
    await runtime.phone_calls.tick(time.time())

    async def changed(*args):
        return {"name": "a different action"}

    monkeypatch.setattr(runtime, "approval_preview", changed)
    await runtime.spoken_approvals.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert runtime.db.one("SELECT voice_status FROM phone_calls")["voice_status"] == "stale"
    assert state["responses"] == 1 and not runtime.spoken_approvals.workers


async def test_restart_preserves_uncertainty_without_retranscribing(
    spoken, scripted_models, checkout_tool
):
    runtime, state = spoken
    await waiting(runtime, scripted_models)
    await runtime.phone_calls.tick(time.time())
    runtime.db.execute("UPDATE phone_calls SET voice_status='processing'")
    runtime.db.recover()
    await runtime.spoken_approvals.tick()
    assert runtime.db.one("SELECT voice_status FROM phone_calls")["voice_status"] == "uncertain"
    assert state["responses"] == 0
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"


@pytest.mark.parametrize("missing", ["asr", "flag"])
async def test_missing_transcription_or_disabled_flag_retains_one_way_alert(
    spoken, scripted_models, checkout_tool, missing
):
    runtime, state = spoken
    await waiting(runtime, scripted_models)
    if missing == "asr":
        runtime.settings.transcription_url = ""
    else:
        runtime.settings.telegram_calls.spoken_approvals = False
    await runtime.phone_calls.tick(time.time())
    assert "interactive" not in state["dialed"][0].url.params
    assert runtime.db.one("SELECT voice_status FROM phone_calls")["voice_status"] is None


def test_large_or_opaque_reviews_are_not_truncated_into_voice_grants():
    row = {
        "tool": "gmail_send_draft",
        "preview": json.dumps(
            {"to": "a@example.test", "body": "x" * 700, "sha256": "digest", "draft_id": "draft"}
        ),
    }
    assert spoken_prompt(row, "Theos") is None
    row = {"tool": "zepto_confirm_cart", "preview": json.dumps({"cart_id": "opaque"})}
    assert spoken_prompt(row, "Theos") is None


def test_short_plain_email_reads_full_contents_and_formatted_recipients():
    row = {
        "tool": "gmail_send_draft",
        "preview": json.dumps(
            {
                "to": "Ada <ada@example.test>",
                "subject": "Meeting",
                "body": "See you tomorrow.",
                "attachments": [],
                "draft_id": "private-draft",
                "sha256": "private-digest",
            }
        ),
    }
    prompt = spoken_prompt(row, "Theos")
    assert "Ada <ada@example.test>" in prompt and "See you tomorrow." in prompt
    assert "private-draft" not in prompt and "private-digest" not in prompt
    row["preview"] = json.dumps({"to": "ada@example.test", "body": "<p>HTML only</p>"})
    assert spoken_prompt(row, "Theos") is None


async def test_runtime_rejects_a_changed_spoken_review_before_reserving_a_turn(
    spoken, scripted_models, checkout_tool
):
    from theos.runtime.approvals import review_digest

    runtime, state = spoken
    session, approval = await waiting(runtime, scripted_models)
    digest = review_digest(approval)
    runtime.db.execute("UPDATE approvals SET preview=?", (json.dumps({"name": "changed"}),))
    with pytest.raises(ValueError, match="changed after the spoken review"):
        runtime.start(
            "alice", session["id"], approval=(approval["id"], True), expected_approval_digest=digest
        )
    assert not runtime.active
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"


async def test_spoken_calls_preserve_the_shared_daily_limit(spoken, scripted_models, checkout_tool):
    runtime, state = spoken
    session, approval = await waiting(runtime, scripted_models)
    runtime.phone_calls.config.daily_limit = 1
    runtime.db.execute(
        "INSERT INTO phone_calls(id,owner,session,kind,source_id,provider,due,expires,status,attempted) VALUES ('quota','alice',?,'request','quota','telegram',?,?,'accepted',?)",
        (session["id"], time.time(), time.time() + 120, time.time()),
    )
    await runtime.phone_calls.tick(time.time())
    assert not state["dialed"] and not state["speech"]
    assert (
        runtime.db.one("SELECT status FROM phone_calls WHERE id=?", (approval["id"],))["status"]
        == "rate_limited"
    )


@pytest.mark.parametrize("case", ["silence", "malformed"])
async def test_missing_or_invalid_audio_never_reaches_transcription(
    spoken, scripted_models, checkout_tool, case
):
    runtime, state = spoken
    await waiting(runtime, scripted_models)
    await runtime.phone_calls.tick(time.time())
    if case == "silence":
        state["response_status"] = 410
    else:
        state["audio"] = b"not-a-wav"
    await runtime.spoken_approvals.tick()
    assert state["asr_count"] == 0
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert runtime.db.one("SELECT voice_status FROM phone_calls")["voice_status"] == (
        "unanswered" if case == "silence" else "unrecognized"
    )


async def test_acknowledgement_cancellation_does_not_erase_or_replay_a_decision(
    spoken, scripted_models, checkout_tool, monkeypatch
):
    runtime, state = spoken
    session, approval = await waiting(runtime, scripted_models)
    await runtime.phone_calls.tick(time.time())

    async def interrupted(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime.spoken_approvals, "feedback", interrupted)
    scripted_models.responses.append([AssistantMessage("Approved action handled.")])
    with pytest.raises(asyncio.CancelledError):
        await runtime.spoken_approvals.tick()
    await asyncio.gather(*runtime.spoken_approvals.workers)
    assert runtime.db.one("SELECT voice_status FROM phone_calls")["voice_status"] == "approved"
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "approved"
    assert len(runtime.db.rows("SELECT * FROM notifications WHERE id LIKE 'voice-decision:%'")) == 1
    await runtime.spoken_approvals.tick()
    assert state["asr_count"] == 1 and state["responses"] == 1
