"""Validate a reviewed subset of tools from an official MCP server."""

import json
import re

from jsonschema import Draft202012Validator, SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness import Tool
from theos.services.errors import ServiceError
from theos.services.result_files import for_model


def local_references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(item, str) or not item.startswith("#")
            ):
                raise ValueError("External schema references are unsupported")
            local_references(item)
    elif isinstance(value, list):
        for item in value:
            local_references(item)


def argument_model(schema, methods):
    """Run remote schema checks before the harness records a started action."""
    local_references(schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    class Arguments(BaseModel):
        model_config = ConfigDict(extra="forbid")
        arguments: dict = Field(default_factory=dict)

        @model_validator(mode="after")
        def check_arguments(self):
            try:
                validator.validate(self.arguments)
                if methods is not None and self.arguments.get("method") not in methods:
                    raise ValueError("This remote method is not enabled for read access.")
            except ValidationError as error:
                raise ValueError("The arguments do not match the remote tool schema.") from error
            return self

    return Arguments


async def account_tools(account, owner, *, result_stager=None):
    account.authorize(owner)
    if not account.connected(owner):
        return []
    try:
        listed = await account.remote(owner)
        tools, seen = [], set()
        for remote in listed:
            if remote.name not in account.spec.read_tools:
                continue
            if remote.name in seen or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", remote.name):
                raise ValueError("Invalid remote tool identity")
            seen.add(remote.name)
            prefix = account.spec.name + "_"
            name = remote.name if remote.name.startswith(prefix) else prefix + remote.name
            if len(name) > 64:
                raise ValueError("Remote tool name is too long")
            schema = remote.inputSchema
            if not isinstance(schema, dict) or len(json.dumps(schema)) > 64000:
                raise ValueError("Unsupported remote schema")
            model = argument_model(schema, account.spec.methods.get(remote.name))

            async def execute(args, ctx, remote_name=remote.name, input_type=model, tool_name=name):
                # Validate again for direct callers that bypass the harness input check.
                input_type.model_validate(args.model_dump())
                account.authorize(owner)
                response = await account.remote(owner, remote_name, args.arguments)
                if response.isError:
                    raise ServiceError(
                        "The account rejected this read. Check access and tool arguments."
                    )
                return await for_model(
                    response.model_dump(mode="json"),
                    tool_name=tool_name,
                    save_result=result_stager,
                )

            description = (
                (remote.description or remote.name)[:4000]
                + "\nRead-only account tool. Large results use a temporary result_file or an incomplete preview. Remote argument schema: "
                + json.dumps(schema, separators=(",", ":"))
            )
            tools.append(Tool(name, description, model, execute, view="mcp_account_read"))
        return tools
    except (ServiceError, PermissionError):
        raise
    except (SchemaError, ValueError, TypeError, AttributeError) as error:
        raise ServiceError(
            "The account tool catalog is unsupported. Check the connection."
        ) from error
