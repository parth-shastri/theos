from __future__ import annotations

from io import StringIO

import pytest
pytest.importorskip("textual")

from rich.console import Console

from harness import (
    Agent,
    AssistantMessage,
    Hooks,
    ImageInput,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    require_approval,
    tool,
)
from harness.testing import FakeModel
from renderer import (
    AgentSession,
    HarnessBinding,
    HarnessTui,
    InteractionReply,
    PromptInput,
    ModelFinished,
    ModelStarted,
    QuestionRequested,
    ReasoningDelta,
    RuntimeInfo,
    RunFinished,
    TextDelta,
)


@pytest.mark.asyncio
async def test_tui_approves_and_resumes_a_local_harness() -> None:
    executions: list[str] = []

    @tool
    def write_file(path: str) -> str:
        """Write a file."""
        executions.append(path)
        return f"wrote {path}"

    agent = Agent(
        FakeModel(
            [
                AssistantMessage(
                    tool_calls=[ToolCall("write-1", "write_file", {"path": "notes.md"})]
                ),
                AssistantMessage(text="Done."),
            ]
        ),
        [write_file],
        hooks=Hooks(before_tool=require_approval("write_file")),
    )
    app = HarnessTui(AgentSession(agent), session_id="default", title="Test")

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#prompt")
        await pilot.press(*"write it")
        await pilot.press("enter")
        await pilot.pause(0.1)

        assert app.screen.query_one("#interaction-title").render() == ("Allow write_file to run?")
        await pilot.click("#allow")
        await pilot.pause(0.1)

        assert executions == ["notes.md"]
        assert app.renderer is not None
        assert app.renderer.assistant_text == "Done."
        assert "fake-1" in str(app.query_one("#status").render())
        assert "    wrote notes.md" in app.renderer.activity
        assert app._busy is False


@pytest.mark.asyncio
async def test_tui_relays_a_structured_question_and_answer() -> None:
    replies: list[InteractionReply] = []

    def stream(prompt: str | None, _session_id: str):
        if prompt is None:
            return [TextDelta(f"Selected {replies[-1].value}"), RunFinished()]
        return [
            QuestionRequested("format", "Choose a format", ("Markdown", "JSON")),
            RunFinished("waiting_for_input"),
        ]

    def respond(values, _session_id: str) -> None:
        replies.extend(values)

    app = HarnessTui(
        HarnessBinding(run=stream, on_respond=respond),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#prompt")
        await pilot.press(*"render")
        await pilot.press("enter")
        await pilot.pause(0.1)
        await pilot.click("#choice-1")
        await pilot.pause(0.1)

        assert replies == [InteractionReply("format", "question", "JSON")]
        assert app.renderer is not None
        assert app.renderer.assistant_text == "Selected JSON"


@pytest.mark.asyncio
async def test_tui_attaches_an_image_with_at_picker_and_backspace_removes_it(
    tmp_path, monkeypatch
) -> None:
    prompts: list[PromptInput | str | None] = []
    image_path = tmp_path / "photos" / "pixel.png"
    image_path.parent.mkdir()
    image_path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44"
            "ae426082"
        )
    )
    monkeypatch.chdir(tmp_path)

    def stream(prompt: PromptInput | str | None, _session_id: str):
        prompts.append(prompt)
        return [TextDelta("I can see it."), RunFinished()]

    app = HarnessTui(
        HarnessBinding(run=stream),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#prompt")
        await pilot.press("@")
        await pilot.pause(0.05)
        menu = app.query_one("#command-menu")
        assert menu.display is True
        assert "photos/" in str(menu.get_option_at_index(0).prompt)
        assert "directory" in str(menu.get_option_at_index(0).prompt)
        await pilot.press("tab")
        await pilot.pause(0.05)
        assert app.query_one("#prompt").value == "@photos/"
        assert "pixel.png" in str(menu.get_option_at_index(0).prompt)
        await pilot.press("tab")
        await pilot.pause(0.05)
        assert len(app._attachments) == 1
        assert app._attachments[0].filename == "pixel.png"
        assert app.query_one("#prompt").value == ""

        await pilot.press("backspace")
        assert app._attachments == []

        await pilot.press("@", "tab", "tab")
        assert len(app._attachments) == 1

        await pilot.press(*"describe it")
        await pilot.press("enter")
        await pilot.pause(0.1)

    assert len(prompts) == 1
    assert isinstance(prompts[0], PromptInput)
    assert prompts[0].text == "describe it"
    assert len(prompts[0].images) == 1
    assert isinstance(prompts[0].images[0], ImageInput)


@pytest.mark.asyncio
async def test_slash_opens_and_filters_the_command_picker() -> None:
    app = HarnessTui(
        HarnessBinding(run=lambda _prompt, _session_id: [RunFinished()]),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#prompt")
        await pilot.press("/")
        await pilot.pause(0.05)

        menu = app.query_one("#command-menu")
        assert menu.display is True
        assert menu.option_count >= 10
        prompts = [
            str(menu.get_option_at_index(index).prompt) for index in range(menu.option_count)
        ]
        assert not any("/image" in prompt or "/remove" in prompt for prompt in prompts)

        await pilot.press(*"res")
        await pilot.pause(0.05)
        assert menu.option_count == 1
        await pilot.press("tab")
        assert app.query_one("#prompt").value == "/resume"
        assert menu.display is False


@pytest.mark.asyncio
async def test_help_is_categorized_and_explains_the_primary_image_flow() -> None:
    app = HarnessTui(
        HarnessBinding(run=lambda _prompt, _session_id: [RunFinished()]),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(110, 45)) as pilot:
        await pilot.click("#prompt")
        await pilot.press(*"/help")
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert app.renderer is not None
        console = Console(record=True, width=110, color_system=None, file=StringIO())
        console.print(*app.renderer.entries)
        rendered = console.export_text()
        assert "HARNESS COMMAND GUIDE" in rendered
        assert "SESSIONS" in rendered
        assert "INSPECT" in rendered
        assert "ATTACH" in rendered
        assert "@" in rendered
        assert "Ctrl+V" in rendered
        assert "Backspace" in rendered
        assert "Find and attach an image file" in rendered
        assert "/image" not in rendered
        assert "/remove" not in rendered


@pytest.mark.asyncio
async def test_resume_opens_saved_session_picker() -> None:
    histories = {
        "default": [UserMessage("current")],
        "saved": [UserMessage("restored")],
    }
    app = HarnessTui(
        HarnessBinding(
            run=lambda _prompt, _session_id: [RunFinished()],
            load_history=lambda session_id: histories[session_id],
            list_sessions=lambda: tuple(histories),
        ),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#prompt")
        await pilot.press(*"/resume")
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert app.screen.query_one("#session-picker-title").render() == "Resume a previous session"
        options = app.screen.query_one("#session-options")
        assert "Restored" in str(options.get_option_at_index(1).prompt)

        await pilot.press("down", "enter")
        await pilot.pause(0.1)

        assert app.session_id == "saved"
        assert app.renderer is not None
        assert app.renderer.session_id == "saved"


@pytest.mark.asyncio
async def test_ctrl_v_attaches_clipboard_image(monkeypatch) -> None:
    image = ImageInput.from_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63f8cfc0f01f00050001ff89993d1d0000000049454e44"
            "ae426082"
        ),
        media_type="image/png",
        filename="clipboard.png",
    )

    async def clipboard_image() -> ImageInput:
        return image

    monkeypatch.setattr("renderer.tui.read_clipboard_image", clipboard_image)
    app = HarnessTui(
        HarnessBinding(run=lambda _prompt, _session_id: [RunFinished()]),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#prompt")
        await pilot.press("ctrl+v")
        await pilot.pause(0.1)

        assert app._attachments == [image]
        assert app.query_one("#attachments").display is True


@pytest.mark.asyncio
async def test_status_and_permissions_show_runtime_details_and_commands() -> None:
    info = RuntimeInfo(
        model="vision-pro-7b",
        provider="local",
        api="chat_completions",
        capabilities=("vision", "tools"),
        tool_names=("read_file", "write_file"),
        permission_policy="Pre-tool policy hook may ask, allow, or deny",
        storage="/tmp/harness.sqlite3",
    )
    app = HarnessTui(
        HarnessBinding(
            run=lambda _prompt, _session_id: [RunFinished()],
            load_history=lambda _session_id: [UserMessage("hello")],
            list_sessions=lambda: ("default", "saved"),
            describe_runtime=lambda _session_id: info,
        ),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(110, 42)) as pilot:
        await pilot.click("#prompt")
        await pilot.press(*"/status")
        await pilot.press("enter")
        await pilot.pause(0.05)
        await pilot.press(*"/permissions")
        await pilot.press("enter")
        await pilot.pause(0.05)

        assert app.renderer is not None
        transcript = _render_transcript(app.renderer)
        assert "⌁ /status" in transcript
        assert "Session status" in transcript
        assert "Ready" in transcript
        assert "LATEST TURN · THIS CLIENT" in transcript
        assert "Not reported" in transcript
        assert "◆" not in transcript
        assert "vision-pro-7b" in transcript
        assert "local · chat_completions" in transcript
        assert "2 saved sessions" in transcript
        assert "⌁ /permissions" in transcript
        assert "PERMISSION BOUNDARY" in transcript
        assert "Allow once or deny with a reason" in transcript


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [40, 80, 110])
async def test_status_wraps_values_and_preserves_run_state(width) -> None:
    from renderer import RunStarted

    app = HarnessTui(
        HarnessBinding(
            run=lambda *_: [],
            describe_runtime=lambda _: RuntimeInfo(model="[bold]literal-model[/bold]"),
        ),
        session_id="session-with-a-long-identifier-1234567890",
    )
    async with app.run_test(size=(width, 40)):
        renderer = app.renderer
        renderer.handle(RunStarted(prompt="hello"))
        renderer.handle(ModelStarted())
        renderer.handle(
            ModelFinished(
                usage={
                    "input_tokens": 1200,
                    "output_tokens": 45,
                    "cached_tokens": 300,
                }
            )
        )
        renderer.handle(RunFinished("waiting_for_input"))
        await app._show_status()
        console = Console(record=True, width=width - 9, color_system=None, file=StringIO())
        console.print(renderer.entries[-1])
        rendered = console.export_text()
        assert max(map(len, rendered.splitlines())) <= width - 9
        # Wrapping must retain the values, including literal Rich markup.
        compact = "".join(rendered.split()).replace("│", "")
        assert "[bold]literal-model[/bold]" in compact
        assert app.session_id in compact
        assert "Waitingforinput" in compact
        assert "1,200input·45output·300cached" in compact

        renderer.fail(RuntimeError("test failure"))
        renderer.set_session(app.session_id, [])
        assert renderer.state == "failed"
        assert renderer.model_calls == 1
        await app._show_status()
        assert "Failed" in _render_transcript(renderer)
        app.session_id = "other"
        renderer.set_session("other", [])
        await app._show_status()
        assert renderer.model_calls == 0
        assert renderer.usage == {}
        console.print(renderer.entries[-1])
        assert "Notreported" in "".join(console.export_text().split()).replace("│", "")


@pytest.mark.asyncio
async def test_thinking_animates_and_expands_reasoning() -> None:
    app = HarnessTui(
        HarnessBinding(run=lambda _prompt, _session_id: [RunFinished()]),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(100, 40)):
        assert app.renderer is not None
        app.renderer.handle(ModelStarted(label="Thinking"))
        block = app.renderer._thinking_blocks[-1]
        first_frame = str(app.renderer.entries[block.index])

        assert app.renderer.animate_thinking() is True
        second_frame = str(app.renderer.entries[block.index])
        assert second_frame != first_frame

        app.renderer.handle(ReasoningDelta("Inspecting the meal and estimating portions."))
        assert "Inspecting the meal" not in str(app.renderer.entries[block.index])

        app.action_toggle_thinking()
        assert "Inspecting the meal" in str(app.renderer.entries[block.index])

        app.renderer.handle(ModelFinished(reasoning="Inspecting the meal and estimating portions."))
        assert "reasoning text not exposed" not in str(app.renderer.entries[block.index])


@pytest.mark.asyncio
async def test_restored_history_keeps_collapsible_reasoning_tools_and_rich_messages() -> None:
    history = [
        UserMessage("Summarize **this** meal."),
        AssistantMessage(
            reasoning="I should inspect the stored meal before answering.",
            tool_calls=[ToolCall("meal-1", "read_meal", {"day": "today"})],
            stop_reason="tool_calls",
            usage={"output_tokens": 24},
        ),
        ToolResultMessage(
            "meal-1",
            "read_meal",
            '{"protein_g": 42}',
            status="completed",
        ),
        AssistantMessage(
            text="## Summary\n\n- **Protein:** 42 g\n- Logged today",
            reasoning="The tool returned a complete meal record.",
            stop_reason="stop",
            usage={"input_tokens": 90, "output_tokens": 18, "cache_read_tokens": 60},
        ),
    ]
    app = HarnessTui(
        HarnessBinding(
            run=lambda _prompt, _session_id: [RunFinished()],
            load_history=lambda _session_id: history,
        ),
        session_id="default",
        title="Test",
    )

    async with app.run_test(size=(110, 45)):
        assert app.renderer is not None
        assert len(app.renderer._thinking_blocks) == 2
        assert len(app.renderer._tool_blocks) == 1
        tool_block = app.renderer._tool_blocks[0]
        thought_block = app.renderer._thinking_blocks[0]
        assert tool_block.status == "completed"
        assert tool_block.output == '{"protein_g": 42}'
        assert "protein_g" not in str(app.renderer.entries[tool_block.index])

        assert app.renderer.toggle_tool(tool_block.index) is True
        assert app.renderer.toggle_thinking(thought_block.index) is True
        assert "protein_g" in str(app.renderer.entries[tool_block.index])
        assert "inspect the stored meal" in str(app.renderer.entries[thought_block.index])

        console = Console(record=True, width=100, color_system=None, file=StringIO())
        console.print(*app.renderer.entries)
        rendered = console.export_text()
        assert "you" in rendered
        assert "Summarize **this** meal." in rendered
        assert "─ response" in rendered
        assert "THEOS" not in rendered
        assert "90 input · 18 output · 60 cached" in rendered
        assert "Summary" in rendered
        assert "Protein: 42 g" in rendered


def _render_transcript(renderer) -> str:
    console = Console(record=True, width=110, color_system=None, file=StringIO())
    console.print(renderer.transcript.content)
    return console.export_text()


@pytest.mark.asyncio
async def test_subagent_tools_and_responses_form_a_collapsible_tree() -> None:
    from renderer import RunStarted, ToolStarted, ToolFinished

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id="default", title="Test")
    async with app.run_test(size=(110, 45)):
        renderer = app.renderer
        assert renderer is not None
        for event in [
            RunStarted(prompt="Plan a meal"),
            ModelStarted(),
            ModelFinished(text="I will ask nutrition.", requested_tools=("nutrition",)),
            ToolStarted("nutrition-1", "nutrition"),
            ModelStarted(parent_call_id="nutrition-1"),
            ToolStarted("research-1", "research", parent_call_id="nutrition-1"),
            ModelStarted(parent_call_id="research-1"),
            ReasoningDelta("Check the food record.", parent_call_id="research-1"),
            ToolStarted("lookup-1", "food_lookup", parent_call_id="research-1"),
            ToolFinished("lookup-1", "food_lookup", "42 g protein", parent_call_id="research-1"),
            ModelStarted(parent_call_id="research-1"),
            TextDelta("Research findings.", parent_call_id="research-1"),
            ModelFinished(text="Research findings.", parent_call_id="research-1"),
            ToolFinished("research-1", "research", "Research complete", parent_call_id="nutrition-1"),
            ModelStarted(parent_call_id="nutrition-1"),
            TextDelta("Nutrition advice.", parent_call_id="nutrition-1"),
            ModelFinished(text="Nutrition advice.", parent_call_id="nutrition-1"),
            ToolFinished("nutrition-1", "nutrition", "Nutrition complete"),
            ModelStarted(),
            TextDelta("Your meal plan."),
            ModelFinished(text="Your meal plan."),
            RunFinished(),
        ]:
            renderer.handle(event)

        rendered = _render_transcript(renderer)
        assert "\n[−]  agent  nutrition" in rendered
        assert "\n    [−]  agent  research" in rendered
        assert "\n        [+]  tool  food lookup" in rendered
        assert rendered.count("─ response") == 1
        assert "Your meal plan." in rendered
        assert "Research findings." not in rendered
        assert "Nutrition advice." not in rendered
        assert "I will ask nutrition." not in rendered
        assert renderer.assistant_text == "Your meal plan."

        responses = list(renderer._responses.values())
        assert [block.collapsible for block in responses] == [True, True, True, False]
        assert renderer.toggle_response(responses[-1].index) is False
        app.action_toggle_response(responses[1].index)
        assert "Research findings." in _render_transcript(renderer)
        renderer.toggle_tool(renderer._tool_blocks[0].index)
        rendered = _render_transcript(renderer)
        assert "agent  research" not in rendered
        assert "Research findings." not in rendered
        assert "Your meal plan." in rendered
        # Keyboard expansion reveals hidden ancestors as well as the leaf.
        renderer.toggle_tool()
        assert "42 g protein" in _render_transcript(renderer)


@pytest.mark.asyncio
async def test_interleaved_subagent_streams_keep_their_own_text_and_reasoning() -> None:
    from renderer import ToolStarted, ToolFinished

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id="default")
    async with app.run_test():
        renderer = app.renderer
        assert renderer is not None
        for event in [
            ToolStarted("a", "agent_a"), ToolStarted("b", "agent_b"),
            ModelStarted(parent_call_id="a"), ModelStarted(parent_call_id="b"),
            ReasoningDelta("A reasoning", parent_call_id="a"),
            ReasoningDelta("B reasoning", parent_call_id="b"),
            TextDelta("A ", parent_call_id="a"), TextDelta("B ", parent_call_id="b"),
            TextDelta("answer", parent_call_id="a"), TextDelta("answer", parent_call_id="b"),
            ModelFinished(parent_call_id="a"), ModelFinished(parent_call_id="b"),
            ToolFinished("b", "agent_b", "B complete"),
            ToolFinished("a", "agent_a", "A complete"),
            ModelStarted(), TextDelta("Main answer"), ModelFinished(), RunFinished(),
        ]:
            renderer.handle(event)
        assert renderer.assistant_text == "Main answer"
        assert [block.content for block in renderer._thinking_blocks[:2]] == ["A reasoning", "B reasoning"]
        assert [block.content for block in renderer._responses.values()] == ["A answer", "B answer", "Main answer"]
        for response in list(renderer._responses.values())[:2]:
            renderer.toggle_response(response.index)
        rendered = _render_transcript(renderer)
        assert "\n[−]  agent  agent a" in rendered
        assert "\n[−]  agent  agent b" in rendered
        assert rendered.count("─ response") == 1


@pytest.mark.asyncio
async def test_restored_history_has_one_main_response_per_user_turn() -> None:
    history = [
        UserMessage("First task"),
        AssistantMessage(text="Working on it", tool_calls=[ToolCall("t", "lookup", {})]),
        ToolResultMessage("t", "lookup", "found"),
        AssistantMessage(text="First answer"),
        UserMessage("Second task"),
        AssistantMessage(text="Checking again"),
        AssistantMessage(text="Second answer"),
    ]
    app = HarnessTui(HarnessBinding(run=lambda *_: [], load_history=lambda _: history), session_id="default")
    async with app.run_test():
        renderer = app.renderer
        assert renderer is not None
        rendered = _render_transcript(renderer)
        assert rendered.count("─ response") == 2
        assert "First answer" in rendered and "Second answer" in rendered
        assert "Working on it" not in rendered and "Checking again" not in rendered


@pytest.mark.asyncio
async def test_new_clears_transcript_and_creates_distinct_empty_sessions() -> None:
    histories = {"default": [UserMessage("Old prompt"), AssistantMessage(text="Old answer")]}
    created = []

    def create(session_id):
        created.append(session_id)
        histories[session_id] = []

    app = HarnessTui(HarnessBinding(
        run=lambda *_: [], load_history=lambda key: histories[key],
        list_sessions=lambda: tuple(histories), ensure_session=create,
    ), session_id="default")
    async with app.run_test() as pilot:
        await pilot.press(*"/new", "enter")
        await pilot.pause()
        first = app.session_id
        assert first != "default"
        assert created == [first]
        assert "Old answer" not in _render_transcript(app.renderer)
        assert "Old prompt" not in _render_transcript(app.renderer)
        assert histories["default"][0].content == "Old prompt"
        assert app.query_one("#prompt").value == ""
        await app._command("/new")
        assert app.session_id not in {first, "default"}
        second = app.session_id
        await app._command("/new default")
        assert app.session_id == second
        await app._command("/session default")
        await app._command("/sessions")
        assert app.session_id == second
        from renderer.tui import _COMMANDS, _HELP_SECTIONS
        assert not any(name in {"/session", "/sessions"} for name, _ in _COMMANDS)
        assert not any(name.startswith("/session") for _, rows in _HELP_SECTIONS for name, _ in rows)


@pytest.mark.asyncio
async def test_resume_search_filter_sort_archive_and_keyboard_navigation(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone
    from dataclasses import replace
    from pathlib import Path
    from renderer.tui import SessionScreen, _SessionChoice

    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=2)).isoformat()
    recent = (now - timedelta(minutes=3)).isoformat()
    cwd = str(Path.cwd().resolve())
    choices = [
        _SessionChoice("a", 2, "", "Plan a workout", old, recent, cwd),
        _SessionChoice("b", 2, "", "Review nutrition", recent, old, cwd),
        _SessionChoice("c", 2, "", "Research recovery", recent, recent, str(tmp_path)),
    ]
    archived = []

    def archive(session_id, value):
        archived.append((session_id, value))

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id="default")
    async with app.run_test(size=(100, 32)) as pilot:
        screen = SessionScreen(choices, "default", archive=archive)
        app.push_screen(screen)
        await pilot.pause()
        options = screen.query_one("#session-options")
        assert [choice.session_id for choice in screen.visible_sessions] == ["a", "b"]
        assert "3m ago" in str(options.get_option_at_index(0).prompt)
        await pilot.click("#session-sort")
        assert [choice.session_id for choice in screen.visible_sessions] == ["b", "a"]
        await pilot.click("#session-filter")
        assert len(screen.visible_sessions) == 3
        await pilot.click("#session-search")
        await pilot.press(*"recovery")
        assert [choice.session_id for choice in screen.visible_sessions] == ["c"]
        await pilot.press("ctrl+a")
        assert archived == [("c", True)]
        assert options.option_count == 0
        assert screen.query_one("#session-empty").display
        await pilot.click("#session-status")
        assert [choice.session_id for choice in screen.visible_sessions] == ["c"]
        await pilot.press("ctrl+a")
        assert archived[-1] == ("c", False)
        await pilot.click("#session-status")
        assert screen.visible_sessions == [replace(choices[2], archived=False)]
        await pilot.click("#session-search")
        screen.query_one("#session-search").value = "no results"
        await pilot.pause()
        assert options.option_count == 0
        await pilot.press("enter")
        assert app.screen is screen
        await pilot.press("escape")
        assert app.screen is not screen


@pytest.mark.asyncio
async def test_transcript_timestamps_are_stable_and_disclosures_have_no_underline() -> None:
    import re
    from renderer import ToolStarted, RunStarted

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id="default")
    async with app.run_test():
        renderer = app.renderer
        renderer.handle(RunStarted(prompt="Hello"))
        renderer.handle(ModelStarted())
        renderer.handle(ReasoningDelta("Reasoning"))
        thought = renderer._thinking_blocks[-1]
        text = renderer.entries[thought.index]
        clickable = [span.style for span in text.spans if getattr(span.style, 'meta', {}).get('@click')]
        assert clickable and all(style.underline is False for style in clickable)
        assert str(renderer.transcript.styles.link_style) == "none"
        renderer.handle(ToolStarted("read", "read_file"))
        assert "[+]  tool  read file" in _render_transcript(renderer)
        renderer.handle(ModelStarted())
        renderer.handle(TextDelta("First "))
        block = list(renderer._responses.values())[-1]
        timestamp = block.timestamp
        renderer.handle(TextDelta("answer"))
        renderer.handle(ModelFinished())
        assert block.timestamp == timestamp
        assert len(re.findall(
            r'\d{1,2}(?:st|nd|rd|th) \w+ \d{2}, \d{2}:\d{2}',
            _render_transcript(renderer),
        )) >= 4
        renderer.set_history(
            [UserMessage("Earlier question"), AssistantMessage(text="Earlier answer")],
            ["2024-05-10T08:30:00+00:00", "2024-05-10T08:31:00+00:00"],
        )
        rendered = _render_transcript(renderer)
        assert rendered.count("10th May 24,") == 2
        assert "Earlier question" in rendered
        renderer.set_title("Updated title")
        assert "Earlier question" in _render_transcript(renderer)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['completed', 'failed'])
async def test_compaction_progress_does_not_warn_and_closes_nested_indicator(status):
    from harness.events import ContextCompaction
    from renderer import ToolStarted
    from renderer.adapters import HarnessAdapter, events

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id='default')
    async with app.run_test():
        renderer = app.renderer
        renderer.handle(ToolStarted('research', 'web_research'))
        adapter = HarnessAdapter()
        for phase in ['started', 'progress', status]:
            raw = ContextCompaction(
                phase, before_tokens=14657, after_tokens=600 if phase == 'completed' else None,
                reason='input_too_large' if phase == 'failed' else None,
                parent_call_id='research',
            )
            for event in events(adapter(raw)):
                assert event.parent_call_id == 'research'
                renderer.handle(event)
            if phase == 'progress':
                assert 'Could not summarize' not in _render_transcript(renderer)
                assert renderer._thinking_blocks[-1].active
        assert not renderer._thinking_blocks[-1].active
        rendered = _render_transcript(renderer)
        if status == 'completed':
            assert '14,657 → 600 tokens' in rendered
            assert 'Could not summarize' not in rendered
        else:
            assert 'Could not summarize earlier conversation (input too large)' in rendered
        assert not renderer._responses


@pytest.mark.asyncio
async def test_only_main_response_shows_usage_even_with_expanded_intermediate_responses():
    from renderer import RunStarted, ToolStarted, ToolFinished
    from renderer.tui import _DETAIL_COLOR

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id='default')
    async with app.run_test(size=(120, 45)):
        renderer = app.renderer
        for event in [
            RunStarted(prompt='Plan lunch'), ModelStarted(),
            ModelFinished(text='**Checking nutrition.**', requested_tools=('nutrition',),
                          usage={'input_tokens': 1000, 'output_tokens': 100}),
            ToolStarted('nutrition', 'nutrition'), ModelStarted(parent_call_id='nutrition'),
            ModelFinished(text='**Nutrition findings.**', parent_call_id='nutrition',
                          usage={'input_tokens': 2000, 'output_tokens': 200}),
            ToolFinished('nutrition', 'nutrition', 'Research complete'),
            ModelStarted(), ModelFinished(text='**Your meal plan.**',
                                          usage={'input_tokens': 90, 'output_tokens': 18}),
            RunFinished(),
        ]:
            renderer.handle(event)
        for block in list(renderer._responses.values())[:-1]:
            renderer.toggle_response(block.index)
        rendered = _render_transcript(renderer)
        assert rendered.count(' input') == 1
        assert rendered.count(' output') == 1
        assert '90 input · 18 output' in rendered
        assert '3,090 in' not in rendered
        assert 'Checking nutrition.' in rendered
        assert 'Nutrition findings.' in rendered
        # Intermediate markdown remains formatted but loses bold emphasis and color accents.
        console = Console(width=120, color_system='truecolor', file=StringIO())
        segments = list(console.render(renderer.transcript.content))
        for segment in segments:
            if 'Checking nutrition.' in segment.text or 'Nutrition findings.' in segment.text:
                assert segment.style.bold is False
                assert segment.style.color.name == _DETAIL_COLOR
        assert any('Your meal plan.' in segment.text and segment.style.bold for segment in segments)


@pytest.mark.asyncio
async def test_replacement_removes_drafts_after_a_later_generation_starts():
    from renderer import RunStarted

    app = HarnessTui(HarnessBinding(run=lambda *_: []), session_id='default')
    async with app.run_test():
        renderer = app.renderer
        for event in [
            RunStarted(prompt='Compare the research'), ModelStarted(),
            TextDelta('Broken first draft'), ModelFinished(text='Broken first draft'),
            ModelStarted(), TextDelta('Broken later draft'),
            ModelFinished(text='Complete replacement with the final source.', replace_answer=True),
            RunFinished('partial'),
        ]:
            renderer.handle(event)
        transcript = _render_transcript(renderer)
        assert 'Broken first draft' not in transcript
        assert 'Broken later draft' not in transcript
        assert 'Complete replacement with the final source.' in transcript
        assert renderer.assistant_text == 'Complete replacement with the final source.'
