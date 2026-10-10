"""Browser API and Telegram transport workflows with fake model streams."""

import httpx
import pytest

from harness import AssistantMessage, ToolCall
from theos.server import create_app
from theos.transports.telegram.polling import Telegram


async def test_browser_chat_upload_settings_dashboard_and_isolation(runtime):
    app = create_app(runtime.settings, runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as browser:
        assert (await browser.get("/live")).status_code == 200
        assert (await browser.get("/ready")).status_code == 200
        assert (await browser.get("/api/sessions")).status_code == 401
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        session = (await browser.post("/api/sessions", json={"title": "Planning"})).json()
        session_id = session["id"]
        upload = await browser.post(
            "/api/files", files={"file": ("notes.txt", b"My notes", "text/plain")}
        )
        assert upload.status_code == 200
        file_id = upload.json()["id"]
        reply = await browser.post(
            f"/api/sessions/{session_id}/turn", json={"text": "Hello", "files": [file_id]}
        )
        assert reply.headers["content-type"].startswith("text/event-stream")
        assert '"type": "text"' in reply.text and '"status": "completed"' in reply.text
        history = (await browser.get(f"/api/sessions/{session_id}")).json()["history"]
        assert file_id in history[0]["content"]
        assert (
            await browser.patch(
                f"/api/sessions/{session_id}",
                json={"model": runtime.settings.model, "reasoning": "low"},
            )
        ).status_code == 200
        assert (
            await browser.patch(f"/api/sessions/{session_id}", json={"model": "not-allowed"})
        ).status_code == 400
        assert (await browser.get("/api/dashboard")).json()["usage"]
        assert (await browser.get(f"/api/files/{file_id}")).content == b"My notes"
        browser.headers["Authorization"] = "Bearer " + "b" * 32
        assert (await browser.get(f"/api/sessions/{session_id}")).status_code == 404
        assert (await browser.get(f"/api/files/{file_id}")).status_code == 404
        assert (await browser.get("/api/dashboard")).status_code == 403
        assert (await browser.get("/api/sessions")).json() == []
        browser.headers["Authorization"] = "Bearer " + "a" * 32
        assert (await browser.post(f"/api/sessions/{session_id}/reset")).status_code == 200
        assert (await browser.get(f"/api/sessions/{session_id}")).json()["history"] == []


@pytest.mark.parametrize("approved", [True, False])
async def test_browser_approval_workflow(runtime, scripted_models, approved):
    app = create_app(runtime.settings, runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as browser:
        session_id = (await browser.post("/api/sessions", json={})).json()["id"]
        scripted_models.responses.append(
            [
                AssistantMessage(
                    tool_calls=[ToolCall("delete", "delete_custom_table", {"name": "notes"})]
                )
            ]
        )
        response = await browser.post(
            f"/api/sessions/{session_id}/turn", json={"text": "Delete notes"}
        )
        assert "waiting_for_approval" in response.text
        pending = (await browser.get(f"/api/sessions/{session_id}")).json()["approvals"][0]
        assert pending["call_id"] == "delete"
        response = await browser.post(
            f"/api/sessions/{session_id}/approvals/{pending['id']}", json={"approved": approved}
        )
        assert response.text.startswith('data: {"type": "approvals", "items": []}\n\n')
        assert '"status": "completed"' in response.text
        assert not (await browser.get(f"/api/sessions/{session_id}")).json()["approvals"]
        assert (
            await browser.post(
                f"/api/sessions/{session_id}/approvals/{pending['id']}",
                json={"approved": approved},
            )
        ).status_code == 400


async def test_upload_limits_and_bad_image(runtime):
    runtime.settings.max_upload_bytes = 1024
    app = create_app(runtime.settings, runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer " + "a" * 32},
    ) as browser:
        assert (
            await browser.post(
                "/api/files", files={"file": ("huge.txt", b"x" * 2000, "text/plain")}
            )
        ).status_code == 400
        assert (
            await browser.post(
                "/api/files", files={"file": ("false.png", b"not an image", "image/png")}
            )
        ).status_code == 400
        assert (
            await browser.post(
                "/api/files", files={"file": ("huge.txt", b"x" * 100000, "text/plain")}
            )
        ).status_code in {400, 413}


def telegram_message(text="Hello", user=123, chat=123, kind="private", topic=None):
    message = {
        "message_id": 1,
        "from": {"id": user},
        "chat": {"id": chat, "type": kind},
        "text": text,
    }
    if topic:
        message["message_thread_id"] = topic
    return {"update_id": 1, "message": message}


async def onboard(telegram, user=123):
    await telegram.handle([telegram_message("/start", user=user, chat=user)])
    await telegram.handle([telegram_message("Test user", user=user, chat=user)])
    await telegram.handle([telegram_message("/skip", user=user, chat=user)])


async def test_telegram_private_group_topics_and_commands(runtime):
    runtime.settings.telegram_users = {123}
    runtime.settings.telegram_chats = {-100}
    telegram = Telegram(runtime)
    calls = []

    async def api(method, payload=None, files=None):
        calls.append((method, payload))
        return {"message_id": len(calls)}

    telegram.api = api
    await onboard(telegram)
    await telegram.handle([telegram_message()])
    assert any(
        m == "editMessageText" and "Hello from the test model" in p["text"] for m, p in calls
    )
    private = runtime.db.one("SELECT * FROM sessions WHERE channel='telegram-private'")
    await telegram.handle([telegram_message("/reasoning high")])
    assert runtime.db.session("telegram:123", private["id"])["reasoning"] == "high"
    await telegram.handle([telegram_message("/reset")])
    assert not runtime.db.load_history("telegram:123", private["id"])
    for topic in (10, 11):
        await telegram.handle([telegram_message(chat=-100, kind="supergroup", topic=topic)])
    groups = runtime.db.rows("SELECT owner,address FROM sessions WHERE channel='telegram-group'")
    assert len(groups) == 2 and groups[0]["owner"] != groups[1]["owner"]
    assert all(g["owner"] != "telegram:123" for g in groups)
    with pytest.raises(PermissionError):
        await telegram.handle([telegram_message(user=999)])
    with pytest.raises(PermissionError):
        await telegram.handle([telegram_message(chat=-999, kind="group")])


async def test_telegram_approval_buttons_and_wrong_chat(runtime, scripted_models):
    runtime.settings.telegram_users = {123, 456}
    telegram = Telegram(runtime)
    calls = []

    async def api(method, payload=None, files=None):
        calls.append((method, payload))
        return {"message_id": len(calls)}

    telegram.api = api
    await onboard(telegram)
    await onboard(telegram, 456)
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("delete", "delete_custom_table", {"name": "notes"})]
            )
        ]
    )
    await telegram.handle([telegram_message("Delete notes")])
    approval_message = next(p for m, p in calls if m == "sendMessage" and "reply_markup" in p)
    data = approval_message["reply_markup"]["inline_keyboard"][0][1]["callback_data"]
    callback = {
        "update_id": 2,
        "callback_query": {
            "id": "cb",
            "from": {"id": 456},
            "message": {"chat": {"id": 456, "type": "private"}},
            "data": data,
        },
    }
    with pytest.raises(ValueError):
        await telegram.handle([callback])
    callback["callback_query"]["from"]["id"] = 123
    callback["callback_query"]["message"]["chat"]["id"] = 123
    await telegram.handle([callback])
    assert (
        runtime.db.one("SELECT status FROM tool_runs WHERE call_id='delete'")["status"] == "denied"
    )


async def test_telegram_album_and_voice_are_one_user_turn(runtime):
    runtime.settings.telegram_users = {123}
    telegram = Telegram(runtime)

    async def api(method, payload=None, files=None):
        return {"message_id": 1}

    telegram.api = api
    await onboard(telegram)
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="JPEG")
    png = output.getvalue()

    async def download(file_id, name, media_type, owner):
        return runtime.files.save(
            owner, name, media_type, png if media_type.startswith("image/") else b"voice"
        )

    telegram.download = download
    photos = []
    for index in range(2):
        update = telegram_message("")
        update["update_id"] = index + 1
        update["message"].update({"media_group_id": "album", "photo": [{"file_id": str(index)}]})
        photos.append(update)
    await telegram.handle(photos)
    session = runtime.db.one("SELECT * FROM sessions")
    history = runtime.db.load_history("telegram:123", session["id"])
    assert len(history[0].images) == 2

    async def transcribe(owner, file_id):
        return "A transcribed voice note"

    runtime.files.transcribe = transcribe
    voice = telegram_message("")
    voice["message"]["voice"] = {"file_id": "voice", "mime_type": "audio/ogg"}
    await telegram.handle([voice])
    assert (
        runtime.db.load_history("telegram:123", session["id"])[2].content
        == "A transcribed voice note"
    )
