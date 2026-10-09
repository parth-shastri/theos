"""Exercise MCP session retention and failure handling through the real SDK."""

import asyncio
import json

import httpx
import pytest

from theos.services.errors import ServiceError
from theos.services.zepto import session as session_module

from .test_zepto import configure_zepto


@pytest.fixture
def remote_server(runtime, monkeypatch):
    configure_zepto(runtime)
    states, calls, deleted = {}, [], []
    entered, release = asyncio.Event(), asyncio.Event()

    async def endpoint(request):
        sid = request.headers.get("mcp-session-id")
        if request.method == "GET":
            return httpx.Response(405)
        if request.method == "DELETE":
            deleted.append(sid)
            states.pop(sid, None)
            return httpx.Response(200)
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "notifications/initialized":
            return httpx.Response(202)
        headers = {}
        if method == "initialize":
            sid = str(len(calls) + 1)
            states[sid] = None
            headers["mcp-session-id"] = sid
            result = {
                "protocolVersion": payload["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-zepto", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": []}
        else:
            name = payload["params"]["name"]
            arguments = payload["params"].get("arguments", {})
            calls.append((sid, name, arguments))
            if name == "fail":
                return httpx.Response(500, text="secret-token")
            if name == "wait":
                entered.set()
                await release.wait()
            if name == "select_saved_address":
                states[sid] = arguments["addressId"]
            result = {
                "content": [{"type": "text", "text": states[sid] or "Store not selected"}],
                "isError": states[sid] is None,
            }
        return httpx.Response(
            200, headers=headers, json={"jsonrpc": "2.0", "id": payload["id"], "result": result}
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        session_module.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(endpoint), **kwargs),
    )
    monkeypatch.setattr(runtime.zepto, "_provider", lambda owner: None)
    return states, calls, deleted, entered, release


async def test_store_survives_discovery_and_search_but_stays_owner_scoped(runtime, remote_server):
    states, calls, deleted, _, _ = remote_server
    await runtime.zepto._remote("telegram:123")
    await runtime.zepto._remote("telegram:123", "select_saved_address", {"addressId": "home"})
    # Runtime discovery happens again before a later conversation turn.
    await runtime.zepto._remote("telegram:123")
    search = await runtime.zepto._remote("telegram:123", "search_products", {"query": "milk"})
    assert not search.isError
    assert search.content[0].text == "home"
    other = await runtime.zepto._remote("telegram:456", "search_products", {"query": "milk"})
    assert other.isError
    assert calls[0][0] == calls[1][0] != calls[2][0]
    assert len(states) == 2
    await runtime.zepto.disconnect("telegram:123")
    assert len(deleted) == 1
    assert "telegram:123" not in runtime.zepto.sessions
    assert "telegram:456" in runtime.zepto.sessions
    await runtime.zepto.close()
    assert len(deleted) == 2
    assert not runtime.zepto.sessions


async def test_failed_action_is_not_replayed_and_next_request_opens_new_session(
    runtime, remote_server
):
    _, calls, _, _, _ = remote_server
    with pytest.raises(ServiceError, match="Check the action result") as failure:
        await runtime.zepto._remote("telegram:123", "fail", {})
    assert "secret-token" not in str(failure.value)
    assert len(calls) == 1
    result = await runtime.zepto._remote("telegram:123", "search_products", {"query": "milk"})
    assert result.isError
    assert len(calls) == 2
    assert calls[0][0] != calls[1][0]


async def test_cancellation_closes_session_and_fails_queued_calls(runtime, remote_server):
    _, calls, _, entered, _ = remote_server
    first = asyncio.create_task(runtime.zepto._remote("telegram:123", "wait", {}))
    await entered.wait()
    second = asyncio.create_task(runtime.zepto._remote("telegram:123", "search_products", {}))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(ServiceError, match="Check the action result"):
        await second
    assert len(calls) == 1


async def test_concurrent_calls_share_session_and_run_in_order(runtime, remote_server):
    states, calls, _, entered, release = remote_server
    first = asyncio.create_task(runtime.zepto._remote("telegram:123", "wait", {}))
    await entered.wait()
    second = asyncio.create_task(
        runtime.zepto._remote("telegram:123", "select_saved_address", {"addressId": "home"})
    )
    await asyncio.sleep(0)
    assert len(calls) == 1
    release.set()
    await asyncio.gather(first, second)
    assert len(states) == 1
    assert [call[1] for call in calls] == ["wait", "select_saved_address"]
