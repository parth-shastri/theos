"""Context boundaries independent of the retired chunked-summary implementation."""

import pytest

from harness import Agent, ContextLimitError, UserMessage
from harness.testing import FakeModel


async def test_unfit_requested_output_without_compaction_stops_before_generation():
    from harness import Hooks

    async def configure(request, ctx):
        request.options["max_output_tokens"] = 8000
        return request

    model = FakeModel([])
    with pytest.raises(ContextLimitError, match="8000 output tokens reserved"):
        await Agent(model, hooks=Hooks(before_model=configure), context_window=10000).run(
            [UserMessage("q" * 9000)]
        )
    assert not model.requests


def test_complete_tool_groups_survive_tail_selection():
    from harness.compression_policy import ContextCompressor

    policy = ContextCompressor(100000, 8192)
    rows = [{"role": "system", "content": "policy"}]
    for i in range(50):
        rows.extend(
            [
                {"role": "user", "content": f"Question {i}"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": str(i), "function": {"name": "read", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": str(i), "content": "facts " * 3000},
                {"role": "assistant", "content": "Finding " * 1000},
            ]
        )
    start, end = policy._compress_window(rows)
    assert rows[start]["role"] != "tool" and rows[end]["role"] != "tool"
    assert rows[-2] in rows[end:] and rows[-1] in rows[end:]


def test_summary_budget_scales_with_middle_size():
    from harness.compression_policy import ContextCompressor

    policy = ContextCompressor(100000, 8192)
    assert policy._compute_summary_budget([{"role": "user", "content": "short"}]) == 2000
    assert policy._compute_summary_budget([{"role": "user", "content": "x" * 300000}]) == 5000


def test_head_protection_decays_after_first_compaction():
    from harness.compression_policy import ContextCompressor

    rows = [{"role": "system", "content": "policy"}] + [{"role": "user", "content": "old"}] * 20
    assert ContextCompressor(100000)._protect_head_size(rows) == 4
    assert (
        ContextCompressor(100000, previous="Prior summary", count=1)._protect_head_size(rows) == 1
    )
