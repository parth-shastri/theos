"""Remote terminal clients share the deployed workspace without owning its runtime."""

import asyncio
import io
from contextlib import asynccontextmanager

import httpx
import pytest
from PIL import Image
from textual.widgets import Input, Select, Static

from harness import AssistantMessage, ImageInput, ToolCall, UserMessage
from harness.events import GenerationComplete
from harness.testing import FakeModel
from renderer.events import ApprovalRequested, ModelFinished, RunFinished, ToolFinished
from renderer.interactive import InteractionReply, PromptInput
from renderer.tui import InteractionScreen, SessionScreen
from theos.server import create_app
from theos.transports.terminal.app import TheosTui
from theos.transports.terminal.cli import build_parser, load_settings, run
from theos.transports.terminal.remote import RemoteSession, server_url
from theos.transports.terminal.screens import SettingsScreen, UsageScreen
from theos.transports.terminal.wire import display_events

from .conftest import call_tool


@pytest.fixture
async def remote(runtime):
    client = RemoteSession(
        "http://test",
        "a" * 32,
        transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
    )
    await client.connect()
    yield client
    await client.close()


async def collect(remote, session_id, prompt="Hello"):
    return [event async for event in remote.stream(prompt, session_id=session_id)]


async def test_remote_and_browser_share_identity_conversations_and_history(remote, runtime):
    browser = runtime.db.create_session(
        "alice", runtime.settings.model, "low", title="Browser chat"
    )
    assert await remote.sessions() == (browser["id"],)
    runtime.db.create_session("bob", runtime.settings.model, "default")
    runtime.db.create_session(
        "terminal:alice", runtime.settings.model, "default", channel="terminal"
    )
    assert await remote.sessions() == (browser["id"],)
    await remote.create_session("remote-chat")
    row = runtime.db.session("alice", "remote-chat")
    assert row["channel"] == "browser"
    output = await collect(remote, "remote-chat")
    assert isinstance(output[-1], RunFinished) and output[-1].status == "completed"
    assert any(isinstance(event, ModelFinished) for event in output)
    saved = await remote.history("remote-chat")
    assert saved[0].content == "Hello" and saved[-1].text == "Hello from the test model."
    snapshot = await remote.request("GET", "api/sessions/remote-chat")
    assert snapshot["history"][-1]["text"] == saved[-1].text
    assert all(await remote.history_timestamps("remote-chat"))
    response = await remote.http.post(
        "api/sessions/remote-chat/turn", json={"text": "From browser"}
    )
    assert response.status_code == 200
    assert (await remote.history("remote-chat"))[-2].content == "From browser"


async def test_remote_authentication_and_owner_channel_isolation(runtime, remote):
    app = create_app(runtime.settings, runtime)
    invalid = RemoteSession("http://test", "invalid" * 6, transport=httpx.ASGITransport(app=app))
    try:
        with pytest.raises(ValueError, match="rejected your token"):
            await invalid.connect()
    finally:
        await invalid.close()
    other = runtime.db.create_session("bob", runtime.settings.model, "default")
    wrong_channel = runtime.db.create_session(
        "alice", runtime.settings.model, "default", channel="terminal"
    )
    for row, error in [(other, LookupError), (wrong_channel, ValueError)]:
        for method, suffix, body in [
            ("POST", "/turn", {"text": "Hi"}),
            ("POST", "/steer", {"text": "Hi"}),
            ("POST", "/resume", {}),
            ("POST", "/decisions", {"replies": [{"request_id": "missing", "approved": True}]}),
            ("PATCH", "", {"title": "Changed"}),
        ]:
            with pytest.raises(error):
                await remote.request(method, remote.path(row["id"], suffix), json=body)
    assert not runtime.active
    assert runtime.db.session("bob", other["id"])["title"] == "New conversation"


async def test_remote_titles_and_archive_state_persist_without_cwd_filter(remote, runtime):
    await remote.create_session("named")
    await remote.rename_session("named", "Shared title")
    await remote.archive_session("named", True)
    details = await remote.session_details()
    assert details[0].title == "Shared title" and details[0].archived
    assert details[0].cwd is None
    assert details[0].created_at and details[0].updated_at
    assert runtime.db.session("alice", "named")["title_auto"] == 0
    with pytest.raises(ValueError, match="already exists"):
        await remote.create_session("named")
    with pytest.raises(ValueError):
        await remote.rename_session("named", "   ")
    with pytest.raises(ValueError):
        await remote.create_session("../path")


async def test_remote_approval_batch_is_atomic_and_browser_can_finish_it(
    remote, runtime, scripted_models
):
    from theos.services.custom_tables.tools import custom_tools

    await remote.create_session("approvals")
    tools = custom_tools(runtime.db, "alice", runtime.settings.data_dir / "tables")
    for name in ["notes", "keep"]:
        await call_tool(tools, "create_custom_table", name=name, columns={"text": "TEXT"})
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("delete-notes", "delete_custom_table", {"name": "notes"}),
                    ToolCall("delete-keep", "delete_custom_table", {"name": "keep"}),
                ]
            )
        ]
    )
    output = await collect(remote, "approvals", "Delete both")
    requests = [event for event in output if isinstance(event, ApprovalRequested)]
    assert len(requests) == 2 and output[-1].status == "waiting_for_approval"
    assert (await collect(remote, "approvals", None))[:-1] == requests
    with pytest.raises(ValueError, match="pending approval"):
        await collect(remote, "approvals", "Ignore approval")
    replies = [
        InteractionReply(requests[0].call_id, "approval", True),
        InteractionReply(requests[1].call_id, "approval", False),
    ]
    with pytest.raises(ValueError, match="absent"):
        await remote.respond(
            [replies[0], InteractionReply("missing", "approval", True)], session_id="approvals"
        )
    assert len(await remote.pending_interactions("approvals")) == 2
    with pytest.raises(ValueError):
        await remote.respond([replies[0], replies[0]], session_id="approvals")
    await remote.respond(replies, session_id="approvals")
    assert not await remote.pending_interactions("approvals")
    with pytest.raises(ValueError, match="already used"):
        await remote.respond(replies, session_id="approvals")
    scripted_models.responses.append([AssistantMessage("Deleted notes and kept the other table.")])
    output = await collect(remote, "approvals", None)
    assert [event.status for event in output if isinstance(event, ToolFinished)] == [
        "completed",
        "denied",
    ]
    assert output[-1].status == "completed"
    # A saved terminal approval also remains actionable through the browser route.
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("delete-again", "delete_custom_table", {"name": "keep"})]
            )
        ]
    )
    await collect(remote, "approvals", "Delete keep")
    request = (await remote.pending_interactions("approvals"))[0]
    scripted_models.responses.append([AssistantMessage("Kept it.")])
    response = await remote.http.post(
        f"api/sessions/approvals/approvals/{request.call_id}", json={"approved": False}
    )
    assert response.status_code == 200 and not await remote.pending_interactions("approvals")


async def test_remote_images_upload_to_the_same_owner_catalog(remote, runtime):
    await remote.create_session("images")
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    image = ImageInput.from_bytes(buffer.getvalue(), media_type="image/png", filename="image.png")
    await collect(remote, "images", PromptInput("Describe", (image,)))
    assert (await remote.history("images"))[0].images[0].url == image.url
    files = runtime.files.list("alice")
    assert len(files) == 1 and files[0]["name"] == "image.png"
    with pytest.raises(LookupError):
        runtime.files.get("bob", files[0]["id"])


async def test_remote_settings_validate_and_usage_shares_saved_accounting(remote, runtime):
    await remote.create_session("settings")
    await remote.save_settings("settings", "qwen-3.8-27b", "xhigh", {"temperature": 0.5})
    config = await remote.configuration("settings")
    assert config["session"]["model"] == "qwen-3.8-27b"
    assert config["session"]["reasoning"] == "xhigh"
    assert config["session"]["generation"] == {"temperature": 0.5}
    with pytest.raises(ValueError):
        await remote.save_settings("settings", "qwen-3.8-27b", "high", {})
    await collect(remote, "settings")
    usage = await remote.usage("settings")
    assert usage["conversation"] == usage["total"]
    assert usage["total"]["requests"] > 0 and usage["total"]["unpriced_requests"] > 0
    info = await remote.runtime_info("settings")
    assert info.model == "qwen-3.8-27b" and "get_preferences" in info.tool_names


async def test_remote_delegate_progress_preserves_scope_and_omits_provider_state(
    remote, scripted_models
):
    await remote.create_session("delegates")
    scripted_models.responses.extend(
        [
            [
                AssistantMessage(
                    tool_calls=[ToolCall("research", "delegate_tasks", {"tasks": ["Read"]})]
                ),
                AssistantMessage("Parent", provider_data={"private": "secret-marker"}),
            ],
            [AssistantMessage("Child")],
        ]
    )
    output = await collect(remote, "delegates")
    assert any(
        isinstance(e, ModelFinished) and e.text == "Child" and e.parent_call_id == "research"
        for e in output
    )
    assert any(isinstance(e, RunFinished) and e.parent_call_id == "research" for e in output)
    assert output[-1].parent_call_id is None
    assert "secret-marker" not in repr(output)
    assert all(event.result is None for event in output if isinstance(event, RunFinished))


async def test_remote_steering_and_simultaneous_turn_rejection(remote, runtime):
    await remote.create_session("steer")
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []

    class PausedModel(FakeModel):
        async def stream(self, request):
            requests.append(request)
            if len(requests) == 1:
                entered.set()
                await release.wait()
            yield GenerationComplete(AssistantMessage("Answer"))

    @asynccontextmanager
    async def models(*_):
        yield PausedModel([])

    runtime.models = models
    task = asyncio.create_task(collect(remote, "steer"))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        with pytest.raises(ValueError, match="running turn"):
            await collect(remote, "steer", "Duplicate")
        await remote.steer("Correction", session_id="steer")
        with pytest.raises(ValueError, match="Finish this turn"):
            await remote.save_settings("steer", "gpt-6-luna", "low", {})
    finally:
        release.set()
    assert (await task)[-1].status == "completed"
    assert any(
        isinstance(m, UserMessage) and m.content == "Correction" for m in requests[1].messages
    )
    with pytest.raises(ValueError):
        await remote.steer("Too late", session_id="steer")


async def test_closing_server_display_stream_does_not_cancel_work(runtime):
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedModel(FakeModel):
        async def stream(self, request):
            entered.set()
            await release.wait()
            yield GenerationComplete(AssistantMessage("Saved after disconnect"))

    @asynccontextmanager
    async def models(*_):
        yield PausedModel([])

    runtime.models = models
    row = runtime.db.create_session("alice", runtime.settings.model, "default")
    turn = runtime.start("alice", row["id"], "Continue", raw_events=True)
    stream = display_events(runtime, turn)
    await anext(stream)
    await asyncio.wait_for(entered.wait(), 3)
    await stream.aclose()
    assert not turn.task.done() and row["id"] in runtime.active
    release.set()
    await turn.task
    assert runtime.db.load_history("alice", row["id"])[-1].text == "Saved after disconnect"


async def test_remote_broken_stream_does_not_replay_the_post():
    posts = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"approvals": []})
        posts.append(request)
        return httpx.Response(
            200,
            headers={"X-Theos-Terminal-Protocol": "1"},
            text='data: {"event":"TextDelta","data":{"text":"Partial","parent_call_id":null}}\n\n',
        )

    remote = RemoteSession("http://test", "a" * 32, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(RuntimeError, match="check saved results"):
            await collect(remote, "lost")
        assert len(posts) == 1
    finally:
        await remote.close()


async def test_remote_cli_does_not_open_sqlite_or_start_a_scheduler(runtime, tmp_path, monkeypatch):
    config = tmp_path / "client.env"
    config.write_text("AGENT_SERVER_URL=http://test\nAGENT_SERVER_TOKEN=" + "a" * 32 + "\n")
    args = build_parser().parse_args(
        ["--config", str(config), "--session", "client", "--prompt", "Hello"]
    )
    original = RemoteSession.__init__

    def initialize(self, url, token):
        original(
            self,
            url,
            token,
            transport=httpx.ASGITransport(app=create_app(runtime.settings, runtime)),
        )

    monkeypatch.setattr(RemoteSession, "__init__", initialize)
    from theos.runtime.scheduler import Scheduler
    from theos.storage.database import Database

    def forbidden(*_):
        raise AssertionError("Remote mode started a local runtime")

    monkeypatch.setattr(Database, "__init__", forbidden)
    monkeypatch.setattr(Scheduler, "__init__", forbidden)
    monkeypatch.setattr("theos.settings.Settings", forbidden)
    seen = []

    async def run_app(app):
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            seen.append((await app.session.history(app.session_id))[-1].text)

    monkeypatch.setattr(TheosTui, "run_async", run_app)
    await run(args)
    assert seen == ["Hello from the test model."]
    assert not (tmp_path / "client-data").exists()


async def test_remote_tui_loads_shared_picker_settings_options_and_usage(remote, runtime):
    row = runtime.db.create_session(
        "alice", runtime.settings.model, "default", title="Browser conversation"
    )
    app = TheosTui(remote, session_id=row["id"], title="Theos", open_session_picker=True)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SessionScreen)
        assert app.screen.visible_sessions[0].title == "Browser conversation"
        await pilot.press("escape")
        await app._command("/settings")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        app.screen.query_one("#settings-model", Select).value = "qwen-3.8-27b"
        await pilot.pause()
        app.screen.query_one("#settings-reasoning", Select).value = "xhigh"
        app.screen.query_one("#parameter-temperature", Input).value = "0.6"
        await pilot.click("#settings-save")
        await pilot.pause()
        assert runtime.db.session("alice", row["id"])["reasoning"] == "xhigh"
        assert app.runtime_info.model == "qwen-3.8-27b"
        await app._command("/reasoning")
        await pilot.pause()
        assert [value for value, _ in app._visible_commands] == [
            "/reasoning default",
            "/reasoning low",
            "/reasoning medium",
            "/reasoning xhigh",
        ]
        await pilot.press("down", "enter")
        assert app.query_one("#prompt", Input).value == "/reasoning low"
        await pilot.press("enter")
        await pilot.pause()
        assert runtime.db.session("alice", row["id"])["reasoning"] == "low"
        await app._command("/reasoning medium")
        assert runtime.db.session("alice", row["id"])["reasoning"] == "medium"
        await app._command("/usage")
        await pilot.pause()
        assert isinstance(app.screen, UsageScreen)
        await pilot.press("escape")
        await app._command("/settings")
        await pilot.pause()
        app.screen.query_one("#settings-model", Select).value = "gpt-6-luna"
        await pilot.pause()
        await pilot.press("escape")
        assert runtime.db.session("alice", row["id"])["model"] == "qwen-3.8-27b"
        await app._command("/continue")
        await pilot.pause()
        assert (await remote.history(row["id"]))[-1].text == "Hello from the test model."


async def test_remote_tui_restores_browser_approval(remote, runtime, scripted_models):
    await remote.create_session("restore")
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[ToolCall("delete", "delete_custom_table", {"name": "notes"})]
            )
        ]
    )
    response = await remote.http.post("api/sessions/restore/turn", json={"text": "Delete notes"})
    assert response.status_code == 200
    scripted_models.responses.append([AssistantMessage("Kept notes.")])
    app = TheosTui(remote, session_id="restore", title="Theos")
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, InteractionScreen)
        await pilot.click("#deny")
        await pilot.pause()
        assert (await remote.history("restore"))[-1].text == "Kept notes."
        assert not runtime.pending("alice", "restore")


def test_remote_configuration_and_url_validation(tmp_path):
    config = tmp_path / "client.env"
    config.write_text(
        "AGENT_SERVER_URL=http://vps.tailnet:8080\nAGENT_SERVER_TOKEN="
        + "a" * 32
        + "\nAGENT_PROVIDER=invalid\nAGENT_GMAIL__CLIENT_ID=unused-local-value\n"
    )
    settings = load_settings(build_parser().parse_args(["--config", str(config)]))
    assert settings.server_url == "http://vps.tailnet:8080"
    assert "a" * 32 not in repr(settings)
    assert server_url("https://vps.tailnet/theos") == "https://vps.tailnet/theos/"
    for url in [
        "file:///data/db",
        "http://user:password@test",
        "http://test?token=secret",
        "http://test/#fragment",
    ]:
        with pytest.raises(ValueError):
            server_url(url)


async def test_remote_settings_screen_preserves_draft_after_server_rejection(remote, runtime):
    await remote.create_session("settings-error")
    app = TheosTui(remote, session_id="settings-error", title="Theos")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await app._command("/settings")
        await pilot.pause()
        app.screen.query_one("#parameter-max_output_tokens", Input).value = "999999"
        await pilot.click("#settings-save")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        assert "token limit" in str(app.screen.query_one("#settings-error", Static).render())
        assert app.screen.query_one("#parameter-max_output_tokens", Input).value == "999999"
        assert not app.screen.saving
        await pilot.press("escape")
