"""Keep freeform calls open while binding decisions to exactly one reviewed action."""

import asyncio
import io
import json
import time
import wave

import httpx
import pytest

from harness import AssistantMessage, ToolCall, UserMessage
from theos.runtime import Runtime
from theos.services.custom_tables.tools import custom_tools

from .conftest import call_tool, collect
from .test_phone_calls import telegram_call_settings as telegram_call_settings


def wav():
    target = io.BytesIO()
    with wave.open(target, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(b"\x00\x04" * 24000)
    return target.getvalue()


def intent(kind, text="", reply="", end=False):
    return [
        AssistantMessage(
            json.dumps(
                {
                    "intent": kind,
                    "reply": reply,
                    "authorization_quote": text if kind in {"approve", "decline"} else "",
                    "end_call": end,
                }
            )
        )
    ]


@pytest.fixture
async def conversation(telegram_call_settings, db, scripted_models):
    settings = telegram_call_settings
    settings.telegram_calls.two_way = True
    settings.transcription_url = "http://transcription.test/v1"
    state = {
        "ordinal": 1,
        "text": "hello",
        "live": True,
        "speech": [],
        "dialed": [],
        "replies": [],
        "asr": 0,
        "during_asr": None,
        "response_status": 200,
        "audio": wav(),
    }

    async def provider(request):
        if request.url.host == "speech.example":
            state["speech"].append(json.loads(request.content)["input"])
            return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"mp3")
        if request.url.host == "transcription.test":
            state["asr"] += 1
            if state["during_asr"]:
                state["during_asr"]()
            return httpx.Response(200, json={"text": state["text"]})
        if request.url.path.endswith("/dialogue"):
            if request.method == "DELETE":
                state["live"] = False
                return httpx.Response(200, json={"status": "closed"})
            return (
                httpx.Response(200, json={"turn": state["ordinal"], "waiting": True})
                if state["live"]
                else httpx.Response(410)
            )
        if request.url.path.endswith("/response"):
            return httpx.Response(
                state["response_status"],
                headers={"content-type": "audio/wav", "X-Theos-Voice-Turn": str(state["ordinal"])},
                content=state["audio"],
            )
        if request.url.path.endswith("/finish"):
            state["replies"].append(dict(request.url.params))
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


async def start(runtime, scripted_models, approval=False):
    session = runtime.db.create_session("alice", "fake", "default")
    if approval:
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
        await collect(runtime.start("alice", session["id"], "Prepare the action"))
        runtime.db.execute("UPDATE phone_calls SET due=?", (time.time() - 1,))
    else:
        with runtime.db.transaction():
            runtime.phone_calls.queue("alice", session["id"], "Your reminder is ready.")
    await runtime.phone_calls.tick(time.time())
    return session


async def test_approval_question_natural_consent_followup_and_goodbye_share_one_call(
    conversation, scripted_models, checkout_tool
):
    runtime, state = conversation
    session = await start(runtime, scripted_models, approval=True)
    assert len(state["dialed"]) == 1 and state["dialed"][0].url.params["interactive"] == "true"
    state["text"] = "Wait, what action do you want to take?"
    scripted_models.responses.append(
        intent("message", reply="The pending request is to confirm the notes action.")
    )
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert state["replies"][-1]["end"] == "false"
    state.update(ordinal=2, text="That looks right, please go ahead with it.")
    scripted_models.responses.extend(
        [intent("approve", state["text"]), [AssistantMessage("The action is complete.")]]
    )
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "approved"
    assert state["replies"][-1]["end"] == "false"
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id='checkout'")["status"]
        == "completed"
    )
    state.update(ordinal=3, text="What happened after that?")
    scripted_models.responses.extend(
        [
            intent("message"),
            [AssistantMessage("The reviewed action completed. What else would you like?")],
        ]
    )
    await runtime.call_conversations.tick()
    assert any(
        isinstance(message, UserMessage) and message.content == state["text"]
        for message in runtime.db.load_history("alice", session["id"])
    )
    state.update(ordinal=4, text="That is everything, goodbye for now.")
    scripted_models.responses.append(intent("end", reply="Goodbye.", end=True))
    await runtime.call_conversations.tick()
    assert state["replies"][-1]["end"] == "true"
    assert (
        runtime.db.one("SELECT conversation_status FROM phone_calls")["conversation_status"]
        == "closed"
    )
    assert len(state["dialed"]) == 1
    assert [
        row["status"]
        for row in runtime.db.rows("SELECT status FROM call_utterances ORDER BY ordinal")
    ] == ["replied", "approved", "replied", "ended"]


async def test_normal_call_accepts_unrelated_sentences_and_stays_open(
    conversation, scripted_models, monkeypatch
):
    runtime, state = conversation
    session = await start(runtime, scripted_models)
    contexts = []
    original = runtime.start

    def capture_context(*args, **kwargs):
        contexts.append(kwargs.get("voice_context"))
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "start", capture_context)
    state["text"] = "Purple elephants. Can you help me think through an idea?"
    scripted_models.responses.extend(
        [intent("message"), [AssistantMessage("Tell me about your idea.")]]
    )
    await runtime.call_conversations.tick()
    assert state["replies"][-1]["end"] == "false"
    assert (
        runtime.db.one("SELECT conversation_status FROM phone_calls")["conversation_status"]
        == "active"
    )
    assert runtime.db.load_history("alice", session["id"])[0].content == state["text"]
    assert contexts[0][0]["reply_text"] == "Your reminder is ready."
    await runtime.call_conversations.tick()
    assert state["asr"] == 1 and len(state["replies"]) == 1


async def test_end_call_does_not_decline_a_pending_approval(
    conversation, scripted_models, checkout_tool
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "Please hang up. I will decide later in the app."
    scripted_models.responses.append(
        intent("end", reply="No decision has been recorded. Goodbye.", end=True)
    )
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert not runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")


async def test_hangup_during_understanding_does_not_authorize_an_action(
    conversation, scripted_models, checkout_tool
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "Yes, please approve that action."
    state["during_asr"] = lambda: state.update(live=False)
    scripted_models.responses.append(intent("approve", state["text"]))
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert not runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")


async def test_an_approval_cannot_cherry_pick_yes_from_a_contradictory_sentence(
    conversation, scripted_models, checkout_tool
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "Yes I understand, but do not approve it."
    scripted_models.responses.append(intent("approve", "Yes", reply=""))
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert state["replies"][-1]["end"] == "false"


@pytest.mark.parametrize("change", ["review", "expiry", "access", "recipient", "resolved", "flag"])
async def test_changed_authority_during_transcription_cannot_use_old_consent(
    conversation, scripted_models, checkout_tool, change
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "That looks good. Please go ahead."

    def mutate():
        if change == "review":
            runtime.db.execute("UPDATE approvals SET preview=?", (json.dumps({"name": "other"}),))
        elif change == "expiry":
            runtime.db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
        elif change == "access":
            runtime.settings.users = {}
        elif change == "recipient":
            runtime.settings.telegram_calls.recipients = {"alice": 987}
        elif change == "flag":
            runtime.settings.telegram_calls.two_way = False
        else:
            runtime.db.execute("UPDATE approvals SET status='denied'")

    state["during_asr"] = mutate
    scripted_models.responses.append(intent("approve", state["text"]))
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] != "approved"
    assert not runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")


async def test_preview_change_during_intent_model_cannot_apply_consent(
    conversation, scripted_models, checkout_tool, monkeypatch
):
    from theos.services import call_conversations

    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "Please approve it and hang up."
    scripted_models.responses.append(intent("approve", state["text"], end=True))
    original = call_conversations.classify

    async def changed(*args):
        result = await original(*args)
        runtime.db.execute("UPDATE approvals SET preview=?", (json.dumps({"name": "changed"}),))
        return result

    monkeypatch.setattr(call_conversations, "classify", changed)
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert not runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")


async def test_changed_provider_preview_cannot_use_the_spoken_grant(
    conversation, scripted_models, checkout_tool, monkeypatch
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "Yes, please approve it."
    scripted_models.responses.append(intent("approve", state["text"]))

    async def changed(*args):
        return {"name": "a different action"}

    monkeypatch.setattr(runtime, "approval_preview", changed)
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert not runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")


@pytest.mark.parametrize("kind,expected", [("approve", "approved"), ("decline", "denied")])
async def test_explicit_decision_can_also_end_the_call(
    conversation, scripted_models, checkout_tool, kind, expected
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "Please decide that action and finish this call."
    scripted_models.responses.extend(
        [intent(kind, state["text"], end=True), [AssistantMessage("Decision handled.")]]
    )
    await runtime.call_conversations.tick()
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == expected
    assert state["asr"] == 1 and state["replies"][-1]["end"] == "true"
    assert len(runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")) == 1
    assert not runtime.db.rows("SELECT * FROM files")


async def test_restart_does_not_replay_an_interrupted_voice_turn(conversation, scripted_models):
    runtime, state = conversation
    await start(runtime, scripted_models)
    job = runtime.db.one("SELECT * FROM phone_calls")
    runtime.db.execute(
        "INSERT INTO call_utterances(call_id,ordinal,status,response_digest,created) VALUES (?,1,'processing','digest',?)",
        (job["id"], time.time()),
    )
    runtime.db.recover()
    await runtime.call_conversations.tick()
    assert state["asr"] == 0
    assert runtime.db.one("SELECT status FROM call_utterances")["status"] == "uncertain"
    assert (
        runtime.db.one("SELECT conversation_status FROM phone_calls")["conversation_status"]
        == "uncertain"
    )


async def test_lost_feedback_keeps_a_recorded_decision_and_never_replays_it(
    conversation, scripted_models, checkout_tool, monkeypatch
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    state["text"] = "That is correct. Please send it."
    scripted_models.responses.extend(
        [intent("approve", state["text"]), [AssistantMessage("Decision handled.")]]
    )

    async def interrupted(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime.call_conversations, "reply", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await runtime.call_conversations.tick()
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "approved"
    assert runtime.db.one("SELECT status FROM call_utterances")["status"] == "approved"
    assert state["asr"] == 1
    assert len(runtime.db.rows("SELECT * FROM tool_runs WHERE call_id='checkout'")) == 1


@pytest.mark.parametrize("case", ["silence", "malformed"])
async def test_missing_or_invalid_audio_cannot_reach_the_model(
    conversation, scripted_models, checkout_tool, case
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    if case == "silence":
        state["response_status"] = 410
    else:
        state["audio"] = b"not-a-wav"
    await runtime.call_conversations.tick()
    assert state["asr"] == 0
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"


async def test_unparseable_intent_asks_again_without_deciding(
    conversation, scripted_models, checkout_tool
):
    runtime, state = conversation
    await start(runtime, scripted_models, approval=True)
    scripted_models.responses.append([AssistantMessage("not valid JSON")])
    await runtime.call_conversations.tick()
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"
    assert state["replies"][-1]["end"] == "false"


@pytest.mark.parametrize("missing", ["asr", "flag"])
async def test_missing_configuration_retains_one_way_call(conversation, scripted_models, missing):
    runtime, state = conversation
    if missing == "asr":
        runtime.settings.transcription_url = ""
    else:
        runtime.settings.telegram_calls.two_way = False
    await start(runtime, scripted_models)
    assert "interactive" not in state["dialed"][0].url.params
    assert (
        runtime.db.one("SELECT conversation_status FROM phone_calls")["conversation_status"] is None
    )


async def test_runtime_rejects_a_changed_review_before_reserving_a_turn(
    conversation, scripted_models, checkout_tool
):
    from theos.runtime.approvals import review_digest

    runtime, state = conversation
    session = await start(runtime, scripted_models, approval=True)
    approval = runtime.db.one("SELECT * FROM approvals")
    digest = review_digest(approval)
    runtime.db.execute("UPDATE approvals SET preview=?", (json.dumps({"name": "changed"}),))
    with pytest.raises(ValueError, match="changed after the spoken review"):
        runtime.start(
            "alice", session["id"], approval=(approval["id"], True), expected_approval_digest=digest
        )
    assert not runtime.active
    assert runtime.db.one("SELECT status FROM approvals")["status"] == "pending"


async def test_two_way_call_preserves_the_shared_daily_limit(conversation, scripted_models):
    runtime, state = conversation
    runtime.phone_calls.config.daily_limit = 0
    await start(runtime, scripted_models)
    assert not state["dialed"] and not state["speech"]
    assert runtime.db.one("SELECT status FROM phone_calls")["status"] == "rate_limited"
