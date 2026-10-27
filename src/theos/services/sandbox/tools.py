"""Commands, image inspection, and response attachments in an owned workspace."""

import mimetypes
import re
import shlex
from datetime import timedelta
from pathlib import PurePosixPath
from typing import Annotated

from pydantic import Field

from harness import RunContext, tool


def sandbox_tools(client, owner, session_id):
    """Expose execution and delivery. The runtime owns all file transfers."""

    @tool
    async def run_command(
        ctx: RunContext,
        command: Annotated[str | None, Field(min_length=1)] = None,
        timeout: Annotated[int, Field(ge=1, le=60)] = 60,
        inspect_images: Annotated[list[str], Field(max_length=8)] | None = None,
    ):
        """Run a shell command from /workspace, or a standalone agent-browser command in your persistent browser. List image paths in inspect_images to see their pixels after execution. Omit command for image inspection only. Use shell commands for Python and all file operations."""
        if not command and not inspect_images:
            raise ValueError("Supply a command or image paths to inspect.")
        sandbox = await client.get(owner, session_id)
        result = {}
        if command:
            from opensandbox.models.execd import RunCommandOpts

            # Only standalone browser commands enter the managed browser. The runtime
            # chooses the owner and tab, rather than accepting identity from CLI flags.
            args = shlex.split(command) if re.match(r"^\s*agent-browser(?:\s|$)", command) else []
            if args and args[0] == "agent-browser":
                if any(value in {"&&", "||", "|", ";", "&", ">", ">>", "<"} for value in args):
                    raise ValueError("Use one standalone agent-browser command per call.")
                if client.browsers is None:
                    raise ValueError("The persistent browser is unavailable.")
                result = await client.browsers.execute(owner, session_id, args[1:], sandbox)
            else:
                executed = await sandbox.commands.run(
                    command,
                    opts=RunCommandOpts(
                        working_directory="/workspace", timeout=timedelta(seconds=timeout)
                    ),
                )
                result = executed.model_dump(mode="json")
        # A failed image read must not disguise a command that already ran as safe to retry.
        inspected, errors = [], []
        for requested in inspect_images or []:
            try:
                path = client.workspace_path(requested)
                data = await client.read_bytes(sandbox, path)
                media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if not media_type.startswith("image/"):
                    raise ValueError("Select an image file.")
                row = client.files.save(owner, PurePosixPath(path).name, media_type, data)
                ctx.state.setdefault("view_images", []).append(row["id"])
                inspected.append(path)
            except Exception as error:
                errors.append({"path": requested, "error": type(error).__name__})
        if inspect_images:
            result.update(inspected_images=inspected, image_errors=errors)
        return result

    @tool
    async def attach_file(path: str):
        """Attach a file from /workspace to your response. The attachment retains this exact file version."""
        path = client.workspace_path(path)
        sandbox = await client.get(owner, session_id)
        data = await client.read_bytes(sandbox, path)
        row = client.files.save(
            owner,
            PurePosixPath(path).name,
            mimetypes.guess_type(path)[0] or "application/octet-stream",
            data,
        )
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    return [run_command, attach_file]
