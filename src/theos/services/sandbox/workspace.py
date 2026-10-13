"""Managed sandbox workspaces with automatic, versioned R2 checkpoints."""

import asyncio
import base64
import hashlib
import shlex
from dataclasses import replace
from pathlib import PurePosixPath

ROOT = "/workspace"
INSTRUCTIONS = (
    "Use the sandbox as your normal workspace whenever computation, data processing, scripts, "
    "document creation, or file inspection helps complete the task. The user does not need to request it. "
    "Keep task files under /workspace. Save intermediate tables and scripts as well as final reports. "
    "Files in this directory are checkpointed automatically after execution. "
    "Use source_to_workspace to transfer complete connector results without copying them through chat. "
    "Read selected rows or file sections and keep exact source IDs in derived data. "
    "Check your calculations and generated files before delivery. "
    "Existing approval requirements still apply. Never claim an R2 save succeeded while its status is pending."
)


class Workspaces:
    def __init__(self, runtime):
        self.runtime = runtime
        self.locks = {}
        self.ready = set()
        self.prepare_locks = {}

    def path(self, path):
        parsed = PurePosixPath(path)
        full = parsed if parsed.is_absolute() else PurePosixPath(ROOT) / parsed
        if ".." in full.parts or not full.is_relative_to(ROOT):
            raise ValueError("Use a path inside /workspace for task files.")
        return str(full)

    async def entries(self, sandbox):
        from opensandbox.models.filesystem import DirectoryListEntry

        pending, visited, result = [ROOT], set(), {}
        while pending:
            directory = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            entries = await sandbox.files.list_directory(
                DirectoryListEntry(path=directory, depth=1)
            )
            for entry in entries:
                row = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry
                path = self.path(row["path"])
                result[path] = row
                if row.get("entry_type") in {"directory", "dir"} and path not in visited:
                    pending.append(path)
        return list(result.values())

    async def prepare(self, owner, session):
        sandbox = await self.runtime.sandboxes.get(owner, session)
        key = (owner, session, sandbox.id)
        lock = self.prepare_locks.setdefault((owner, session), asyncio.Lock())
        async with lock:
            if key in self.ready:
                return sandbox
            result = await sandbox.commands.run("mkdir -p /workspace")
            if getattr(result, "error", None):
                raise RuntimeError("The sandbox could not create its workspace.")
            try:
                manifest = self.runtime.db.record(owner, "workspace", session)
            except LookupError:
                manifest = {"files": {}}
            existing = {entry["path"] for entry in await self.entries(sandbox)}
            for path, info in manifest["files"].items():
                # Keep work newer than the checkpoint when reconnecting to a live sandbox.
                if path in existing:
                    continue
                saved = await self.runtime.checkpoints.get(owner, session, info["source_id"])
                path = self.path(path)
                await sandbox.commands.run(
                    "mkdir -p " + shlex.quote(str(PurePosixPath(path).parent))
                )
                await sandbox.files.write_file(path, base64.b64decode(saved["data"]))
            self.ready.add(key)
        return sandbox

    async def write(self, owner, session, path, content):
        sandbox = await self.prepare(owner, session)
        path = self.path(path)
        await sandbox.commands.run("mkdir -p " + shlex.quote(str(PurePosixPath(path).parent)))
        await sandbox.files.write_file(path, content)
        manifest = await self.save(owner, session)
        return {"path": path, "workspace": manifest}

    async def save(self, owner, session):
        lock = self.locks.setdefault((owner, session), asyncio.Lock())
        async with lock:
            sandbox = await self.runtime.sandboxes.get(owner, session)
            try:
                previous = self.runtime.db.record(owner, "workspace", session)
            except LookupError:
                previous = {"files": {}}
            files = {}
            for row in await self.entries(sandbox):
                if row.get("entry_type") not in {"file", "regular"}:
                    continue
                path = self.path(row["path"])
                data = await sandbox.files.read_bytes(
                    path, limit=self.runtime.settings.max_upload_bytes + 1
                )
                if len(data) > self.runtime.settings.max_upload_bytes:
                    raise ValueError(
                        f"Workspace file exceeds the configured transfer limit: {path}"
                    )
                digest = hashlib.sha256(data).hexdigest()
                prior = previous["files"].get(path)
                if prior and prior["digest"] == digest:
                    files[path] = prior
                    continue
                source = await self.runtime.checkpoints.put(
                    owner,
                    session,
                    "workspace_file",
                    {
                        "path": path,
                        "data": base64.b64encode(data).decode(),
                        "digest": digest,
                    },
                )
                files[path] = {
                    "source_id": source,
                    "digest": digest,
                    "version": prior["version"] + 1 if prior else 1,
                }
            manifest = {"files": files}
            self.runtime.db.put_record(owner, "workspace", session, manifest)
            return manifest

    def wrap(self, original, owner, session):
        if original.name not in {
            "sandbox_run_command",
            "sandbox_execute_code",
            "sandbox_write_file",
            "sandbox_upload_file",
            "sandbox_browser",
            "sandbox_send_file_to_user",
            "sandbox_read_file",
            "sandbox_list_files",
            "sandbox_view_image",
        }:
            return original

        async def execute(args, ctx):
            await self.prepare(owner, session)
            try:
                return await original.execute(args, ctx)
            finally:
                # A failed command can still create useful files. Preserve them before returning.
                await self.save(owner, session)

        return replace(original, execute=execute)
