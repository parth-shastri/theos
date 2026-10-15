"""Sandbox execution, file, browser, and lifecycle tools."""

import asyncio
import mimetypes
import shlex
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Literal

from harness import tool

from .workspace import ROOT


def sandbox_tools(client, owner, session_id):
    """Build execution and file tools for one conversation sandbox."""

    def workspace_path(path):
        parsed = PurePosixPath(path)
        return str(parsed if parsed.is_absolute() else PurePosixPath(ROOT) / parsed)

    @tool
    async def run_command(command: str, timeout: int = 60):
        """Run a shell command in your task workspace, starting from /workspace."""
        from opensandbox.models.execd import RunCommandOpts

        sandbox = await client.get(owner, session_id)
        result = await sandbox.commands.run(
            command,
            opts=RunCommandOpts(
                working_directory="/workspace", timeout=timedelta(seconds=min(120, max(1, timeout)))
            ),
        )
        return result.model_dump(mode="json")

    @tool
    async def execute_code(code: str):
        """Run Python in your persistent task workspace.

        Variables and imports persist between calls.
        """
        from code_interpreter import CodeInterpreter, SupportedLanguage

        interpreter = await CodeInterpreter.create(sandbox=await client.get(owner, session_id))
        result = await asyncio.wait_for(
            interpreter.codes.run(
                "import os; os.chdir('/workspace')\n" + code, language=SupportedLanguage.PYTHON
            ),
            timeout=60,
        )
        return result.model_dump(mode="json")

    @tool
    async def write_file(path: str, content: str):
        """Write a text file in your task workspace."""
        sandbox = await client.get(owner, session_id)
        await sandbox.files.write_file(workspace_path(path), content)
        return {"path": path}

    @tool
    async def read_file(path: str):
        """Read a text file from your task workspace."""
        sandbox = await client.get(owner, session_id)
        return {"content": await sandbox.files.read_file(workspace_path(path), limit=64000)}

    @tool
    async def list_files(path: str = "/workspace"):
        """List files in a task workspace directory."""
        sandbox = await client.get(owner, session_id)
        from opensandbox.models.filesystem import DirectoryListEntry

        result = await sandbox.files.list_directory(DirectoryListEntry(path=workspace_path(path)))
        return (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else [r.model_dump(mode="json") for r in result]
        )

    @tool
    async def send_file_to_user(path: str):
        """Share a file from your task workspace with the user."""
        sandbox = await client.get(owner, session_id)
        data = await sandbox.files.read_bytes(
            workspace_path(path), limit=client.settings.max_upload_bytes + 1
        )
        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        row = client.files.save(owner, PurePosixPath(path).name, media_type, data)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @tool
    async def view_image(path: str):
        """Load an image from your task workspace for visual inspection."""
        sandbox = await client.get(owner, session_id)
        data = await sandbox.files.read_bytes(
            workspace_path(path), limit=client.settings.max_upload_bytes + 1
        )
        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if not media_type.startswith("image/"):
            raise ValueError("Select an image file.")
        row = client.files.save(owner, PurePosixPath(path).name, media_type, data)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @tool
    async def upload_file(file_id: str, path: str):
        """Copy one of your uploaded files into your task workspace."""
        row = client.files.get(owner, file_id)
        sandbox = await client.get(owner, session_id)
        await sandbox.files.write_file(workspace_path(path), Path(row["path"]).read_bytes())
        return {"path": path}

    @tool
    async def browser(arguments: list[str]):
        """Open pages and interact with them.

        Use open, snapshot, click, fill, or screenshot commands.
        """
        sandbox = await client.get(owner, session_id)
        result = await sandbox.commands.run(shlex.join(["agent-browser", *arguments]))
        return result.model_dump(mode="json")

    @tool
    async def manage_workspace(
        action: Literal["status", "renew", "restart", "destroy", "forget"],
    ):
        """Check your workspace, restart it, or clear its saved state."""
        if action == "forget":
            return await client.forget(owner, session_id)
        if action in {"destroy", "restart"}:
            await client.destroy(owner, session_id)
            if action == "destroy":
                return {"destroyed": True}
        sandbox = await client.get(owner, session_id)
        info = await sandbox.get_info()
        result = info.model_dump(mode="json")
        if action == "renew":
            result["renewed"] = False
            result["reason"] = "Workspace expiry is fixed from creation and cannot be extended."
        return result

    return [
        run_command,
        execute_code,
        write_file,
        read_file,
        list_files,
        send_file_to_user,
        upload_file,
        view_image,
        browser,
        manage_workspace,
    ]
