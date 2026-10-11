import asyncio
import json
from contextlib import aclosing

import pytest

from harness import (Agent, AssistantMessage, Budget, CompactionConfig, ContextCompaction,
                     ContextMemory, TextDelta, ToolCall, UserMessage)
from harness.limits import HarnessError
from harness.testing import FakeModel
from harness.types import ToolResultMessage, message_to_dict

CONFIG = CompactionConfig('Summarize the supplied conversation.', {'max_tokens': 256}, 128)


@pytest.mark.parametrize('parameter', ['max_output_tokens', 'max_tokens', 'max_completion_tokens'])
@pytest.mark.parametrize('trigger_ratio', [0.6, 1.0])
async def test_requested_output_triggers_compaction_before_the_input_threshold(parameter, trigger_ratio):
    from harness import Hooks
    from harness.model import default_estimate_tokens
    from harness.types import ModelRequest

    history = [UserMessage('Keep source dates.'), AssistantMessage('x' * 6600),
               UserMessage('Keep these requirements. ' + 'q' * 2000)]
    original = [message_to_dict(message) for message in history]
    input_tokens = default_estimate_tokens(ModelRequest(history, []))
    assert input_tokens < 10000 * trigger_ratio
    assert input_tokens + 1024 < 10000 < input_tokens + 8000

    async def configure(request, ctx):
        request.options[parameter] = 8000
        return request

    model = FakeModel([AssistantMessage('Keep the source dates.'), AssistantMessage('Complete answer.')])
    result = await Agent(
        model, hooks=Hooks(before_model=configure), context_window=10000,
        compaction=CompactionConfig('Preserve requirements and sources.', {parameter: 8000},
                                    max_summary_tokens=None, trigger_ratio=trigger_ratio),
    ).run(history, budget=Budget(1), compaction_budget=Budget(5))
    assert result.message.text == 'Complete answer.'
    assert len(model.requests) == 2
    assert [message_to_dict(message) for message in history[:3]] == original
    assert model.requests[-1].messages[-1].content == original[-1]['content']
    for request in model.requests:
        assert request.options[parameter] == 8000
        assert default_estimate_tokens(request) + 8000 <= 10000


async def test_unfit_requested_output_without_compaction_stops_before_generation():
    from harness import ContextLimitError, Hooks

    async def configure(request, ctx):
        request.options['max_output_tokens'] = 8000
        return request

    model = FakeModel([])
    with pytest.raises(ContextLimitError, match='8000 output tokens reserved'):
        await Agent(model, hooks=Hooks(before_model=configure), context_window=10000).run(
            [UserMessage('q' * 9000)])
    assert not model.requests


async def test_explicit_output_setting_replaces_the_larger_generic_space_estimate():
    from harness import Hooks

    async def configure(request, ctx):
        request.options['max_output_tokens'] = 100
        return request

    model = FakeModel([AssistantMessage('Complete answer.')])
    result = await Agent(model, hooks=Hooks(before_model=configure), context_window=500).run(
        [UserMessage('A short question.')])
    assert result.status == 'completed'
    assert model.requests[0].options['max_output_tokens'] == 100


def transcript():
    return [UserMessage('Answer in Hindi. Compare both options. ' + 'a' * 5600),
            AssistantMessage(text='First option examined. ' + 'b' * 5600),
            UserMessage('Continue with the other option.')]


@pytest.mark.asyncio
async def test_bounded_chunks_events_and_reused_memory():
    first = 'User requests Hindi and a comparison. Second option remains unfinished.'
    summary = first + ' The first option has been examined.'
    model = FakeModel([AssistantMessage(text=first), AssistantMessage(text=summary),
                       AssistantMessage(text='Here is the second option.'),
                       AssistantMessage(text='Continuing.')])
    history = transcript()
    current_call = ToolCall('current-evidence', 'lookup', {})
    history.extend([AssistantMessage(tool_calls=[current_call]),
                    ToolResultMessage('current-evidence', 'lookup', 'Current evidence')])
    original_length = len(history)
    original = [message_to_dict(m) for m in history]
    memory, budget = ContextMemory(), Budget(8)
    agent = Agent(model, instructions='Help with the task.', context_window=2000,
                  reserved_output_tokens=256, compaction=CONFIG)
    events = [e async for e in agent.run_stream(history, memory=memory, budget=budget)]
    assert budget.used == 3
    assert memory.covered_messages == 2
    assert memory.summary == summary
    assert [message_to_dict(m) for m in history[:original_length]] == original
    assert first in model.requests[1].messages[-1].content
    assert summary in str(model.requests[2].messages)
    assert all(not r.tools for r in model.requests[:2])
    assert 'current-evidence' in str(model.requests[2].messages)
    assert all('current-evidence' not in str(r.messages) for r in model.requests[:2])
    progress = [e for e in events if isinstance(e, ContextCompaction)]
    assert [e.status for e in progress] == ['started', 'progress', 'progress', 'completed']
    assert progress[-1].model_calls == 2
    assert 'Hindi' not in str(progress)
    assert summary not in [e.text for e in events if isinstance(e, TextDelta)]
    restored = ContextMemory.from_dict(memory.to_dict())
    history.append(UserMessage('Explain further.'))
    events = [e async for e in agent.run_stream(history, memory=restored)]
    assert not any(isinstance(e, ContextCompaction) for e in events)
    assert summary in str(model.requests[-1].messages)


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [AssistantMessage(text=''), AssistantMessage(text='x' * 1000),
    AssistantMessage(text='Incomplete', stop_reason='length'),
    AssistantMessage(tool_calls=[ToolCall('bad', 'log_meal', {})])])
async def test_invalid_summary_preserves_memory_and_history(bad):
    history, memory, events = transcript(), ContextMemory(), []
    original = [message_to_dict(m) for m in history]
    model = FakeModel([bad])
    agent = Agent(model, context_window=2000, reserved_output_tokens=256, compaction=CONFIG)
    with pytest.raises(HarnessError):
        async for event in agent.run_stream(history, memory=memory):
            events.append(event)
    assert memory == ContextMemory()
    assert [message_to_dict(m) for m in history] == original
    assert events[-1].status == 'failed'
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_cancellation_does_not_commit_partial_memory():
    entered = asyncio.Event()
    class WaitingModel:
        async def stream(self, request):
            entered.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover
    memory = ContextMemory()
    agent = Agent(WaitingModel(), context_window=2000,
                  reserved_output_tokens=256, compaction=CONFIG)
    async def consume():
        async with aclosing(agent.run_stream(transcript(), memory=memory)) as events:
            return [e async for e in events]
    running = asyncio.create_task(consume())
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert memory == ContextMemory()


@pytest.mark.asyncio
async def test_later_chunk_failure_keeps_previous_complete_summary():
    history = [UserMessage('Previous preferences'), AssistantMessage(text='Understood.'), *transcript()]
    memory = ContextMemory('Keep the original preferences.', 2)
    original = memory.to_dict()
    model = FakeModel([AssistantMessage(text='Partially updated summary.'), AssistantMessage(text='')])
    agent = Agent(model, context_window=2000, reserved_output_tokens=256, compaction=CONFIG)
    events = []
    with pytest.raises(HarnessError):
        async for event in agent.run_stream(history, memory=memory):
            events.append(event)
    assert memory.to_dict() == original
    assert events[-1].model_calls == 2


@pytest.mark.asyncio
async def test_shared_model_budget_bounds_compaction():
    model, memory, events = FakeModel([]), ContextMemory(), []
    agent = Agent(model, context_window=2000, reserved_output_tokens=256, compaction=CONFIG)
    with pytest.raises(HarnessError):
        async for event in agent.run_stream(transcript(), memory=memory, budget=Budget(1)):
            events.append(event)
    assert not model.requests
    assert events[-1].reason == 'budget_exhausted'
    assert memory == ContextMemory()


@pytest.mark.asyncio
async def test_separate_compaction_budget_preserves_the_research_call():
    summary = 'Keep the Hindi preference and the unfinished comparison.'
    model = FakeModel([AssistantMessage(text=summary), AssistantMessage(text=summary),
                       AssistantMessage(text='Here is the comparison.')])
    research, compact = Budget(1), Budget(2)
    agent = Agent(model, context_window=2000, reserved_output_tokens=256, compaction=CONFIG)
    result = await agent.run(transcript(), budget=research, compaction_budget=compact)
    assert result.status == 'completed'
    assert research.used == 1 and compact.used == 2
    assert len(model.requests) == 3
    assert model.requests[:2][0].messages[0].content == CONFIG.prompt
    assert result.message.text == 'Here is the comparison.'


@pytest.mark.asyncio
@pytest.mark.parametrize('allowance', [0, 1])
async def test_separate_compaction_exhaustion_keeps_memory_and_research(allowance):
    model = FakeModel([AssistantMessage(text='Keep the unfinished comparison.')])
    research, compact, memory = Budget(1), Budget(allowance), ContextMemory()
    agent = Agent(model, context_window=2000, reserved_output_tokens=256, compaction=CONFIG)
    with pytest.raises(HarnessError):
        await agent.run(transcript(), budget=research, compaction_budget=compact, memory=memory)
    assert research.used == 0
    assert compact.used == allowance
    assert len(model.requests) == allowance
    assert memory == ContextMemory()


@pytest.mark.asyncio
async def test_research_reduces_completed_exchanges_inside_one_turn_and_pins_brief():
    history = [UserMessage('Compare versions 2 and 3. Preserve conflicts and source dates.')]
    for i in range(4):
        history += [AssistantMessage(tool_calls=[ToolCall(f'call-{i}', 'search_web', {'query': f'version {i}'})]),
                    ToolResultMessage(f'call-{i}', 'search_web', 'Source findings. ' + 'x' * 3600)]
    original = [message_to_dict(m) for m in history]
    summary = 'Version 2 differs from 3. Source: https://example.org/v2. Conflict remains unresolved.'
    model = FakeModel([AssistantMessage(text=summary)] * 8)
    memory, budget = ContextMemory(), Budget(10)
    agent = Agent(model, context_window=2100, reserved_output_tokens=256,
        compaction=CompactionConfig('Preserve task, findings, citations, and unresolved questions.',
                                    {'max_tokens': 256}, 128, reduce_current_turn=True))
    events = [e async for e in agent.run_stream(history, memory=memory, budget=budget)]
    assert memory.covered_messages > 1 and memory.pinned_messages == [0]
    assert [message_to_dict(m) for m in history[:len(original)]] == original
    request = model.requests[-1]
    assert request.messages[0].content == original[0]['content']
    assert 'call-3' in str(request.messages) and 'call-0' not in str(request.messages)
    assert 'unresolved' in str(request.messages)
    assert ContextMemory.from_dict(memory.to_dict()).view(history) == memory.view(history)
    assert any(isinstance(e, ContextCompaction) and e.status == 'completed' for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize('earlier_exchange', [False, True])
async def test_research_compacts_an_oversized_completed_tool_batch(earlier_exchange):
    """A single model response may return several searches before another model call."""
    from harness.model import default_estimate_tokens

    history = [UserMessage('Compare the sources; preserve dates and conflicting claims.')]
    if earlier_exchange:
        history.extend([
            AssistantMessage(tool_calls=[ToolCall('earlier', 'search_web', {})]),
            ToolResultMessage('earlier', 'search_web', 'Earlier evidence. ' + 'x' * 800),
        ])
    calls = [ToolCall(f'batch-{i}', 'search_web', {'query': str(i)}) for i in range(4)]
    history.extend([
        AssistantMessage(tool_calls=calls),
        *(ToolResultMessage(call.id, call.name,
                           f'https://example.org/{i} Source findings. ' + 'x' * 3600)
          for i, call in enumerate(calls)),
    ])
    original = [message_to_dict(message) for message in history]
    summary = 'Sources disagree. Preserve the dates. See https://example.org/0 and https://example.org/3.'
    model = FakeModel([AssistantMessage(text=summary)] * 10)
    memory = ContextMemory()
    agent = Agent(model, context_window=2100, reserved_output_tokens=256,
                  compaction=CompactionConfig('Summarize findings.', {'max_tokens': 256}, 128,
                                              reduce_current_turn=True))
    events = [event async for event in agent.run_stream(history, memory=memory, budget=Budget(10))]
    assert memory.covered_messages == len(original)
    assert memory.pinned_messages == [0]
    assert [message_to_dict(message) for message in history[:len(original)]] == original
    assert model.requests[-1].messages[0].content == history[0].content
    assert not any(isinstance(message, ToolResultMessage) for message in model.requests[-1].messages)
    assert any(event.status == 'completed' for event in events if isinstance(event, ContextCompaction))
    for request in model.requests:
        assert default_estimate_tokens(request) + request.options.get('max_tokens', 256) <= 2100
    summaries = [json.loads(request.messages[-1].content) for request in model.requests[:-1]]
    assert {message['content'].split()[0] for chunk in summaries for message in chunk['messages']
            if message['role'] == 'tool_result' and message['content'].startswith('https:')} == {
                f'https://example.org/{i}' for i in range(4)}


@pytest.mark.asyncio
async def test_compaction_does_not_summarize_an_unfinished_tool_batch():
    from harness.compaction import compact_context
    from harness.context import default_estimate
    from harness.model import default_estimate_tokens

    async def count(messages):
        return default_estimate(messages)

    async def count_request(request):
        return default_estimate_tokens(request)

    calls = [ToolCall('finished', 'search_web', {}), ToolCall('pending', 'search_web', {})]
    history = [UserMessage('Research the subject.'), AssistantMessage(tool_calls=calls),
               ToolResultMessage('finished', 'search_web', 'x' * 10000)]
    memory, model = ContextMemory(), FakeModel([])
    with pytest.raises(HarnessError):
        async for _ in compact_context(
            history=history, memory=memory,
            config=CompactionConfig('Summarize.', reduce_current_turn=True),
            model=model, budget=Budget(5), count=count, count_request=count_request,
            max_tokens=1500, context_window=2100,
        ):
            pass
    assert memory == ContextMemory()
    assert not model.requests
