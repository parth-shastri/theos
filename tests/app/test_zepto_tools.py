"""Check delivery-store recovery without hidden remote actions."""

from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, TextContent

from theos.services.errors import ServiceError
from theos.services.zepto.tools import zepto_tools

from .conftest import call_tool


@pytest.mark.parametrize("name", ["search_products", "search_multiple_products"])
async def test_search_explains_store_setup_and_does_not_retry(name):
    calls = []

    async def remote(owner, tool=None, arguments=None):
        assert owner == "alice"
        if tool is None:
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name=name,
                        description="Search products",
                        inputSchema={
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    )
                ]
            )
        calls.append((tool, arguments))
        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text="Error: Store not selected. Please use "
                    "get_location_serviceability or select_store first.",
                )
            ],
        )

    client = SimpleNamespace(
        authorize=lambda owner: None, connected=lambda owner: True, _remote=remote
    )
    tools = await zepto_tools(client, "alice")
    assert "zepto_select_saved_address" in tools[0].description
    assert "Ask which address" in tools[0].description
    assert "do not require approval" in tools[0].description
    with pytest.raises(ServiceError, match="chosen address") as failure:
        await call_tool(tools, "zepto_" + name, arguments={"query": "milk"})
    assert "retry the search" in str(failure.value)
    assert calls == [(name, {"query": "milk"})]


async def test_unknown_provider_error_does_not_expose_remote_body():
    async def remote(owner, name=None, arguments=None):
        if name is None:
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(name="search_products", description="Search", inputSchema={})
                ]
            )
        return CallToolResult(
            isError=True,
            content=[TextContent(type="text", text="Upstream failed: Bearer secret-token")],
        )

    client = SimpleNamespace(
        authorize=lambda owner: None, connected=lambda owner: True, _remote=remote
    )
    tools = await zepto_tools(client, "alice")
    with pytest.raises(ServiceError) as failure:
        await call_tool(tools, "zepto_search_products", arguments={"query": "milk"})
    assert "secret-token" not in str(failure.value)
    assert "Zepto rejected" in str(failure.value)
