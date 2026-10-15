"""Expose validated tools discovered from the connected Zepto MCP server."""

import json

from jsonschema import ValidationError, validate
from pydantic import BaseModel, Field

from harness import Tool
from theos.services.errors import ServiceError

STORE_REQUIRED = (
    "Zepto has no selected delivery store. Use zepto_list_saved_addresses, then "
    "zepto_select_saved_address with the user's chosen address. Alternatively, use "
    "zepto_get_location_serviceability for the user's delivery coordinates or "
    "zepto_select_store with a store ID returned by Zepto. Then retry the search."
)


def request_error(response):
    """Translate known prerequisites without exposing arbitrary remote error bodies."""
    for block in response.content:
        if block.type == "text" and "store not selected" in block.text.casefold():
            return STORE_REQUIRED
    return "Zepto rejected the request. Check the connected account."


class ZeptoArguments(BaseModel):
    """Wrap one remote MCP tool's validated argument object."""

    arguments: dict = Field(default_factory=dict)


async def zepto_tools(client, owner):
    """Discover remote tools only for the connected private owner."""
    client.authorize(owner)
    if not client.connected(owner):
        return []
    try:
        listed = await client._remote(owner)
    except Exception as error:
        raise ServiceError(
            "Zepto is unavailable. Check the connection or reconnect the account."
        ) from error
    result = []
    for remote in listed.tools:
        if remote.name == "zepto_shop":
            continue

        async def execute(args, ctx, name=remote.name, schema=remote.inputSchema):
            try:
                validate(args.arguments, schema)
            except ValidationError as error:
                raise ValueError("The Zepto arguments do not match the tool schema.") from error
            try:
                response = await client._remote(owner, name, args.arguments)
            except ServiceError:
                raise
            except Exception as error:
                raise ServiceError(
                    "Zepto is unavailable. Check the connection or reconnect the account."
                ) from error
            if response.isError:
                raise ServiceError(request_error(response))
            return response.model_dump(mode="json")

        description = (
            (remote.description or remote.name)
            + "\nRemote argument schema: "
            + json.dumps(remote.inputSchema)
        )
        if remote.name in {"search_products", "search_multiple_products"}:
            description += (
                "\nBefore searching, establish a delivery store if none is selected. "
                "Use zepto_list_saved_addresses and zepto_select_saved_address for the "
                "user's chosen saved address. Ask which address to use if unclear. "
                "For a new location, use zepto_get_location_serviceability with the "
                "user's delivery coordinates. Use only address or store IDs returned "
                "by Zepto. Store setup and searches do not require approval. "
                "If Zepto reports no selected store, complete this setup before retrying."
            )
        result.append(Tool("zepto_" + remote.name, description, ZeptoArguments, execute))
    return result
