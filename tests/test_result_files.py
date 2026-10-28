"""Large provider results stay inspectable without filling the model request."""

import pytest

from theos.services.result_files import PREVIEW_BYTES, for_model


async def test_small_result_stays_inline():
    value = {"days": [{"date": "2026-10-18", "steps": 12}]}

    assert await for_model(value, tool_name="get_health_summary") is value


async def test_large_result_returns_a_temporary_file_pointer():
    saved = {}

    async def save_result(name, content):
        saved.update(name=name, content=content)
        return {"path": "/tmp/theos-results/result.json"}

    result = await for_model(
        {"body": "x" * 9000},
        tool_name="gmail_get_message",
        summary="Message msg1 has 9,000 body characters.",
        save_result=save_result,
    )

    assert result["result_file"] == "/tmp/theos-results/result.json"
    assert result["summary"] == "Message msg1 has 9,000 body characters."
    assert result["result_bytes"] == len(saved["content"].encode("utf-8"))
    assert result["truncated"] is False
    assert saved["name"] == "gmail_get_message"
    assert "run_command" in result["message"]


async def test_failed_staging_returns_a_bounded_preview():
    async def fail_to_save(_name, _content):
        raise OSError("sandbox unavailable")

    result = await for_model(
        {"body": "x" * 9000}, tool_name="gmail_get_message", save_result=fail_to_save
    )

    assert result["truncated"] is True
    assert len(result["preview"].encode("utf-8")) <= PREVIEW_BYTES
    assert result["result_bytes"] > PREVIEW_BYTES
    assert "narrower arguments" in result["message"]


async def test_results_over_the_file_limit_do_not_get_staged():
    async def save_result(*_args):
        pytest.fail("an oversized result must not be written to the sandbox")

    result = await for_model(
        {"body": "x" * (1024 * 1024 + 1)},
        tool_name="gmail_get_message",
        save_result=save_result,
    )

    assert result["truncated"] is True
    assert len(result["preview"].encode("utf-8")) <= PREVIEW_BYTES
