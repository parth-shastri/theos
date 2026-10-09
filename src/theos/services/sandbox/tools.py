"""Sandbox execution, file, browser, and lifecycle tools."""

import asyncio
import mimetypes
import shlex
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Literal

from harness import tool


def sandbox_tools(client, owner, session_id):
    """Build execution and file tools for one conversation sandbox."""

    @tool
    async def sandbox_run_command(command: str, timeout: int = 60):
        """Run a shell command in your remote sandbox after confirmation."""
        from opensandbox.models.execd import RunCommandOpts

        sandbox = await client.get(owner, session_id)
        result = await sandbox.commands.run(
            command, opts=RunCommandOpts(timeout=timedelta(seconds=min(120, max(1, timeout))))
        )
        return result.model_dump(mode="json")

    @tool
    async def sandbox_execute_code(code: str):
        """Run Python in your remote sandbox's persistent interpreter."""
        from code_interpreter import CodeInterpreter, SupportedLanguage

        interpreter = await CodeInterpreter.create(sandbox=await client.get(owner, session_id))
        result = await asyncio.wait_for(
            interpreter.codes.run(code, language=SupportedLanguage.PYTHON), timeout=60
        )
        return result.model_dump(mode="json")

    @tool
    async def sandbox_write_file(path: str, content: str):
        """Write a text file in the remote sandbox."""
        sandbox = await client.get(owner, session_id)
        await sandbox.files.write_file(path, content)
        return {"path": path}

    @tool
    async def sandbox_read_file(path: str):
        """Read a text file from the remote sandbox."""
        sandbox = await client.get(owner, session_id)
        return {"content": await sandbox.files.read_file(path, limit=64000)}

    @tool
    async def sandbox_list_files(path: str = "/tmp"):
        """List files in a remote sandbox directory."""
        sandbox = await client.get(owner, session_id)
        from opensandbox.models.filesystem import DirectoryListEntry

        result = await sandbox.files.list_directory(DirectoryListEntry(path=path))
        return (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else [r.model_dump(mode="json") for r in result]
        )

    @tool
    async def sandbox_send_file_to_user(path: str):
        """Download a generated sandbox file and deliver it to the user."""
        sandbox = await client.get(owner, session_id)
        data = await sandbox.files.read_bytes(path, limit=client.settings.max_upload_bytes + 1)
        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        row = client.files.save(owner, PurePosixPath(path).name, media_type, data)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @tool
    async def sandbox_view_image(path: str):
        """Read a sandbox image and attach it to the next model request."""
        sandbox = await client.get(owner, session_id)
        data = await sandbox.files.read_bytes(path, limit=client.settings.max_upload_bytes + 1)
        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if not media_type.startswith("image/"):
            raise ValueError("Select an image file.")
        row = client.files.save(owner, PurePosixPath(path).name, media_type, data)
        return {"file_id": row["id"], "name": row["name"], "media_type": row["media_type"]}

    @tool
    async def sandbox_upload_file(file_id: str, path: str):
        """Copy one of your uploaded files into the remote sandbox."""
        row = client.files.get(owner, file_id)
        sandbox = await client.get(owner, session_id)
        await sandbox.files.write_file(path, Path(row["path"]).read_bytes())
        return {"path": path}

    @tool
    async def sandbox_browser(arguments: list[str]):
        """Run agent-browser in the sandbox. Use snapshot, open, click, fill, or screenshot commands."""
        sandbox = await client.get(owner, session_id)
        result = await sandbox.commands.run(shlex.join(["agent-browser", *arguments]))
        return result.model_dump(mode="json")

    @tool
    async def sandbox_lifecycle(action: Literal["status", "renew", "destroy", "forget"]):
        """Inspect, extend, destroy, or forget an expired sandbox."""
        if action == "forget":
            old = client.clients.pop((owner, session_id), None)
            if old:
                await old.close()
            return client.db.delete_record(owner, "sandbox", session_id)
        sandbox = await client.get(owner, session_id)
        if action == "destroy":
            await sandbox.kill()
            await sandbox.close()
            client.clients.pop((owner, session_id), None)
            return client.db.delete_record(owner, "sandbox", session_id)
        if action == "renew":
            await sandbox.renew(timedelta(seconds=client.settings.sandbox.timeout_seconds))
        info = await sandbox.get_info()
        return info.model_dump(mode="json")

    return [
        sandbox_run_command,
        sandbox_execute_code,
        sandbox_write_file,
        sandbox_read_file,
        sandbox_list_files,
        sandbox_send_file_to_user,
        sandbox_upload_file,
        sandbox_view_image,
        sandbox_browser,
        sandbox_lifecycle,
    ]
