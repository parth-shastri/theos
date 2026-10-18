"""Managed sandbox workspaces with automatic, versioned R2 checkpoints."""

import asyncio
import base64
import hashlib
import shlex
from dataclasses import replace
from pathlib import PurePosixPath

from harness import OutcomeUnknown
from theos.prompts import render
from theos.services.errors import ServiceError

from .errors import WorkspaceUnavailable

ROOT = "/workspace"
INSTRUCTIONS = render("capabilities/sandbox.md")

RETRYABLE_WORKSPACE_FAILURE = (
    "The requested action did not start because the workspace could not be reached. "
    "Saved files remain available. Retry this same tool once with the same arguments; "
    "the runtime will handle reconnection and restoration."
)
RETRYABLE_STATUS_CODES = {404, 408, 410, 425, 429, 500, 502, 503, 504}


def retryable_workspace_error(error):
    """Recognize connection and missing-instance errors before user work starts."""
    import httpx

    return (
        isinstance(error, (WorkspaceUnavailable, httpx.RequestError, TimeoutError))
        or getattr(error, "status_code", None) in RETRYABLE_STATUS_CODES
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
                raise RuntimeError("The task workspace could not be prepared.")
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
        try:
            sandbox = await self.prepare(owner, session)
        except Exception as error:
            if not retryable_workspace_error(error):
                raise
            raise ServiceError(RETRYABLE_WORKSPACE_FAILURE) from error
        path = self.path(path)
        await sandbox.commands.run("mkdir -p " + shlex.quote(str(PurePosixPath(path).parent)))
        await sandbox.files.write_file(path, content)
        try:
            manifest = await self.save(owner, session)
        except Exception as error:
            raise OutcomeUnknown(
                "The workspace file may have been written, but its saved state could not "
                "be confirmed. Do not repeat this operation automatically."
            ) from error
        return {"path": path, "workspace": manifest}

    async def save(self, owner, session):
        lock = self.locks.setdefault((owner, session), asyncio.Lock())
        async with lock:
            sandbox = await self.prepare(owner, session)
            try:
                previous = self.runtime.db.record(owner, "workspace", session)
            except LookupError:
                previous = {"files": {}}
            files = {}
            for row in await self.entries(sandbox):
                if row.get("entry_type") not in {"file", "regular"}:
                    continue
                path = self.path(row["path"])
                # Line-based limits would rewrite binary files before hashing and restore.
                data = await sandbox.files.read_bytes(
                    path, range_header=f"bytes=0-{self.runtime.settings.max_upload_bytes}"
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
        workspace_tools = {
            "run_command",
            "execute_code",
            "write_file",
            "upload_file",
            "browser",
            "send_file_to_user",
            "read_file",
            "list_files",
            "view_image",
        }
        if original.name not in workspace_tools:
            return original
        saves_workspace = original.name in {
            "run_command",
            "execute_code",
            "write_file",
            "upload_file",
            "browser",
        }

        async def execute(args, ctx):
            try:
                await self.prepare(owner, session)
            except Exception as error:
                if not retryable_workspace_error(error):
                    raise
                raise ServiceError(RETRYABLE_WORKSPACE_FAILURE) from error

            try:
                result = await original.execute(args, ctx)
            except WorkspaceUnavailable as error:
                # Every workspace tool acquires its connection before doing the requested work.
                raise ServiceError(RETRYABLE_WORKSPACE_FAILURE) from error
            except BaseException as operation_error:
                # An operation may fail after changing files, so save its partial work.
                if not saves_workspace:
                    raise
                try:
                    await self.save(owner, session)
                except Exception as save_error:
                    if not isinstance(operation_error, Exception):
                        raise operation_error from None
                    raise OutcomeUnknown(
                        "The workspace operation may have started, but its result and file "
                        "changes could not be confirmed. Do not repeat it automatically."
                    ) from save_error
                raise

            # Reads and file delivery cannot change /workspace, so they need no R2 write.
            if not saves_workspace:
                return result
            try:
                await self.save(owner, session)
            except Exception as save_error:
                raise OutcomeUnknown(
                    "The workspace operation may have completed, but its file changes could "
                    "not be saved. Do not repeat it automatically."
                ) from save_error
            return result

        return replace(original, execute=execute)
