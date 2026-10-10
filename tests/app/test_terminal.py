"""Terminal transport acceptance through the durable application runtime."""

import asyncio
import io
import time
from contextlib import asynccontextmanager

import pytest
from PIL import Image

from harness import AssistantMessage, ImageInput, ToolCall, UserMessage
from harness.events import GenerationComplete
from harness.testing import FakeModel
from renderer.events import ApprovalRequested, ModelFinished, Notice, RunFinished, ToolFinished
from renderer.interactive import InteractionReply, PromptInput
from renderer.tui import InteractionScreen
from theos.runtime.scheduler import Scheduler
from theos.transports.terminal.app import TheosTui
from theos.transports.terminal.cli import build_parser, load_settings, run
from theos.transports.terminal.session import TerminalSession

from .conftest import call_tool


@pytest.fixture
def terminal(runtime):
    session = TerminalSession(runtime, "terminal:alice")
    session.create_session("local")
    return session


async def collect(session, prompt="Hello", session_id="local"):
    return [event async for event in session.stream(prompt, session_id=session_id)]


async def test_terminal_stream_uses_application_tools_and_saves_history(terminal, scripted_models):
    scripted_models.responses.append(
        [
            AssistantMessage(tool_calls=[ToolCall("preferences", "get_preferences", {})]),
            AssistantMessage(
                "Your preferences.",
                reasoning="Read saved preferences.",
                usage={"input_tokens": 42, "output_tokens": 6},
            ),
        ]
    )
    output = await collect(terminal)
    assert any(isinstance(e, ToolFinished) and e.call_id == "preferences" for e in output)
    model = [e for e in output if isinstance(e, ModelFinished)][-1]
    assert model.reasoning == "Read saved preferences."
    assert model.usage["input_tokens"] == 42
    assert output[-1] == RunFinished("completed")
    assert terminal.history("local")[-1].text == "Your preferences."
    times = terminal.history_timestamps("local")
    restored = TerminalSession(terminal.runtime, terminal.owner)
    assert restored.history_timestamps("local") == times
    assert restored.history("local") == terminal.history("local")
    info = await restored.runtime_info("local")
    assert "get_preferences" in info.tool_names and info.storage.endswith("theos.sqlite3")
    assert "gmail_send_draft" not in info.tool_names


async def test_terminal_approval_batch_survives_adapter_restart(terminal, scripted_models):
    from theos.services.custom_tables.tools import custom_tools

    runtime = terminal.runtime
    tools = custom_tools(runtime.db, terminal.owner, runtime.settings.data_dir / "tables")
    for name in ("notes", "keep"):
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
    output = await collect(terminal, "Delete both tables")
    requests = [e for e in output if isinstance(e, ApprovalRequested)]
    assert len(requests) == 2 and output[-1].status == "waiting_for_approval"
    assert "local" not in runtime.active
    assert '"name": "notes"' in requests[0].reason
    restored = TerminalSession(runtime, terminal.owner)
    assert [
        e for e in await collect(restored, None) if isinstance(e, ApprovalRequested)
    ] == requests
    with pytest.raises(ValueError):
        await collect(restored, "Skip approval")
    replies = [
        InteractionReply(requests[0].call_id, "approval", True),
        InteractionReply(requests[1].call_id, "approval", False),
    ]
    with pytest.raises(ValueError):
        restored.respond(
            [replies[0], InteractionReply("missing", "approval", True)], session_id="local"
        )
    assert len(restored.pending_interactions("local")) == 2
    restored.respond(replies, session_id="local")
    scripted_models.responses.append([AssistantMessage("Deleted notes. Kept the other table.")])
    output = await collect(restored, None)
    assert [e.status for e in output if isinstance(e, ToolFinished)] == ["completed", "denied"]
    assert output[-1].status == "completed"
    with pytest.raises(ValueError):
        restored.respond(replies, session_id="local")
    tables = await call_tool(tools, "list_custom_tables_and_templates")
    assert "keep" in str(tables) and "notes" not in str(tables)


async def test_terminal_owner_and_transport_isolation(terminal):
    other = TerminalSession(terminal.runtime, "terminal:bob")
    other.create_session("other")
    for operation in (other.history, other.session_title, other.pending_interactions):
        with pytest.raises(LookupError):
            operation("local")
    with pytest.raises(LookupError):
        await collect(other)
    assert other.sessions() == ("other",)
    browser = terminal.db.create_session(terminal.owner, "test", "default")
    with pytest.raises(LookupError):
        terminal.history(browser["id"])
    with pytest.raises(ValueError):
        TerminalSession(terminal.runtime, "telegram:123")
    with pytest.raises(ValueError):
        terminal.create_session("other")


async def test_terminal_image_enters_owned_file_catalog(terminal):
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    image = ImageInput.from_bytes(buffer.getvalue(), media_type="image/png", filename="sample.png")
    await collect(terminal, PromptInput("Describe this", (image,)))
    message = terminal.history("local")[0]
    assert message.images[0].url == image.url
    files = terminal.runtime.files.list(terminal.owner)
    assert len(files) == 1 and files[0]["name"] == "sample.png"
    with pytest.raises(LookupError):
        terminal.runtime.files.get("terminal:bob", files[0]["id"])


async def test_terminal_steering_reaches_next_model_request(terminal):
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

    terminal.runtime.models = models
    task = asyncio.create_task(collect(terminal, "First"))
    await asyncio.wait_for(entered.wait(), 3)
    terminal.steer("Change the plan", session_id="local")
    release.set()
    output = await task
    assert output[-1].status == "completed" and len(requests) == 2
    assert any(
        isinstance(m, UserMessage) and m.content == "Change the plan" for m in requests[1].messages
    )
    assert terminal.history("local")[-2].content == "Change the plan"
    with pytest.raises(ValueError):
        terminal.steer("Too late", session_id="local")


async def test_terminal_cancellation_saves_interrupted_state_and_unconsumed_input(terminal):
    entered = asyncio.Event()

    class BlockedModel(FakeModel):
        async def stream(self, request):
            entered.set()
            await asyncio.Event().wait()
            yield GenerationComplete(AssistantMessage("Unreachable"))

    @asynccontextmanager
    async def models(*_):
        yield BlockedModel([])

    terminal.runtime.models = models
    task = asyncio.create_task(collect(terminal))
    await asyncio.wait_for(entered.wait(), 3)
    terminal.steer("Save this correction", session_id="local")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not terminal.runtime.active
    assert terminal.history("local")[-1].content == "Save this correction"
    assert terminal._session("local")["status"] == "interrupted"


async def test_terminal_failure_is_visible_and_releases_turn(terminal, scripted_models):
    scripted_models.responses.append([RuntimeError("provider failed")])
    output = await collect(terminal)
    assert any(
        isinstance(e, ModelFinished) and (e.text or "").startswith("Partial answer:")
        for e in output
    )
    assert not any(isinstance(e, Notice) and e.level == "error" for e in output)
    assert output[-1].status == "partial" and not terminal.runtime.active


async def test_terminal_delegate_events_retain_parent_scope(terminal, scripted_models):
    scripted_models.responses.extend(
        [
            [
                AssistantMessage(
                    tool_calls=[ToolCall("research", "delegate_tasks", {"tasks": ["Read"]})]
                ),
                AssistantMessage("Parent answer"),
            ],
            [AssistantMessage("Child answer")],
        ]
    )
    output = await collect(terminal)
    children = [e for e in output if e.parent_call_id == "research"]
    assert any(isinstance(e, ModelFinished) and e.text == "Child answer" for e in children)
    assert any(isinstance(e, RunFinished) for e in children)
    assert output[-1].status == "completed" and output[-1].parent_call_id is None


async def test_terminal_sessions_keep_directory_archive_and_manual_title(terminal):
    terminal.rename_session("local", "My title")
    terminal.archive_session("local", True)
    await collect(terminal)
    restored = TerminalSession(terminal.runtime, terminal.owner)
    detail = restored.session_details()[0]
    assert detail.title == "My title" and detail.archived and detail.cwd
    assert detail.created_at and detail.updated_at


async def test_terminal_scheduled_turn_and_reminder_notices(terminal, scripted_models):
    from .test_automation import schedule

    runtime = terminal.runtime
    row = runtime.session(terminal.owner, "local")
    await schedule(runtime, row)
    scripted_models.responses.append([AssistantMessage("Scheduled answer")])
    scheduler = Scheduler(runtime)
    scheduler.scheduled.tick(time.time())
    await asyncio.gather(*scheduler.scheduled.workers)
    scheduler.scheduled.tick(time.time())
    assert runtime.db.one("SELECT COUNT(*) n FROM scheduled_runs")["n"] == 1
    assert terminal.notifications()[0]["text"] == "Scheduled answer"
    assert terminal.notifications() == []
    await scheduler.close()


async def test_terminal_tui_restores_saved_approval_and_resumes_once(terminal, scripted_models):
    scripted_models.responses.append(
        [
            AssistantMessage(
                tool_calls=[
                    ToolCall("delete", "delete_custom_table", {"name": "notes"}),
                ]
            )
        ]
    )
    await collect(terminal)
    scripted_models.responses.append([AssistantMessage("Denied as requested.")])
    app = TheosTui(terminal, session_id="local", title="Theos")
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, InteractionScreen)
        await pilot.click("#deny")
        await pilot.pause()
        assert terminal.history("local")[-1].text == "Denied as requested."
        assert not app._busy
        await app._command("/new")
        assert app.session_id != "local" and terminal.history(app.session_id) == []


async def test_terminal_tui_polls_background_notices_after_startup(terminal):
    from rich.console import Console

    terminal.db.execute(
        "INSERT INTO notifications VALUES (?,?,?,?,?,0)",
        ("reminder", terminal.owner, "local", "Drink water", time.time()),
    )
    app = TheosTui(terminal, session_id="local", title="Theos")
    async with app.run_test(size=(100, 35)) as pilot:
        await pilot.pause(1.3)
        assert terminal.db.one("SELECT delivered FROM notifications")["delivered"] == 1
        output = io.StringIO()
        Console(file=output).print(app.renderer.transcript.content)
        assert "Drink water" in output.getvalue()


def test_terminal_settings_work_outside_the_source_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_DATA_DIR", raising=False)
    args = build_parser().parse_args([])
    config = tmp_path / "profile.env"
    config.write_text("AGENT_PROVIDER=fake\nAGENT_DATA_DIR=state\nAGENT_NAME=Local\n")
    args.config = config
    settings = load_settings(args)
    assert settings.data_dir == tmp_path / "state" and settings.name == "Local"
    args.data_dir = tmp_path / "override"
    assert load_settings(args).data_dir == args.data_dir
    args.config = tmp_path / "absent"
    with pytest.raises(ValueError):
        load_settings(args)


async def test_terminal_cli_shutdown_releases_database(tmp_path, monkeypatch):
    from theos.storage.database import Database

    config = tmp_path / "test.env"
    config.write_text("AGENT_PROVIDER=fake\nAGENT_NAME=Test\n")
    args = build_parser().parse_args(
        [
            "--config",
            str(config),
            "--data-dir",
            str(tmp_path / "data"),
            "--prompt",
            "Hello",
        ]
    )
    seen = []

    async def run_app(app):
        async with app.run_test() as pilot:
            await pilot.pause()
            seen.append(app.session.history(app.session_id)[-1].text)

    monkeypatch.setattr(TheosTui, "run_async", run_app)
    await run(args)
    assert seen == ["Test is ready. This is a local test response."]
    db = Database(tmp_path / "data")
    db.close()
