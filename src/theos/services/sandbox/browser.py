"""Owner-scoped browsers independent of task sandbox lifetimes."""

import asyncio
import hashlib
import json
import logging
import os
import shlex
import time
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from opensandbox.models.execd import RunCommandOpts

from harness import OutcomeUnknown
from theos.services.errors import ServiceError

from .client import Sandboxes

logger = logging.getLogger("theos")
PROFILE = "/tmp/theos-browser/profile"
ARCHIVE = "/tmp/theos-browser/profile.tar.gz"
MAX_PROFILE_BYTES = 64 * 1024 * 1024
# Owner, daemon, transport, and profile flags belong to the runtime.
ACTIONS = {
    "open",
    "goto",
    "navigate",
    "snapshot",
    "read",
    "click",
    "dblclick",
    "fill",
    "type",
    "press",
    "hover",
    "focus",
    "select",
    "check",
    "uncheck",
    "scroll",
    "scrollintoview",
    "back",
    "forward",
    "reload",
    "get",
    "is",
    "wait",
    "eval",
    "screenshot",
    "pdf",
    "download",
    "upload",
    "keyboard",
    "mouse",
    "frame",
    "dialog",
}
FORBIDDEN_FLAGS = {
    "--session",
    "--session-name",
    "--namespace",
    "--profile",
    "--state",
    "--restore",
    "--cdp",
    "--auto-connect",
    "--provider",
    "-p",
    "--config",
    "--executable-path",
    "--extension",
    "--extensions",
    "--headers",
    "--new-tab",
    "--proxy",
    "--proxy-bypass",
    "--args",
    "--engine",
}


def payload(result):
    """Read the CLI's JSON envelope without placing profile commands in history."""
    stdout = "".join(line.text for line in result.logs.stdout)
    try:
        return json.loads(stdout)
    except ValueError:
        raise ServiceError("The browser returned an invalid command result.") from None


class Browsers:
    def __init__(self, runtime):
        self.runtime = runtime
        self.boxes = Sandboxes(runtime.settings, runtime.db, runtime.files)
        self.locks = {}
        self.ready = set()
        self.cipher = None

    def encryption(self):
        if self.cipher is None:
            # The key never enters a sandbox. Stopped-application backups include it.
            path = self.runtime.settings.data_dir / "browser.key"
            if not path.exists():
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(Fernet.generate_key())
                    stream.flush()
                    os.fsync(stream.fileno())
            self.cipher = Fernet(path.read_bytes())
        return self.cipher

    def status(self, owner):
        saved = self.runtime.db.one(
            "SELECT updated FROM credentials WHERE owner=? AND service='browser'", (owner,)
        )
        return {
            "configured": self.runtime.settings.sandbox.enabled,
            "saved": bool(saved),
            "updated": saved["updated"] if saved else None,
        }

    async def cli(self, sandbox, args):
        result = await sandbox.commands.run(
            shlex.join(["agent-browser", "--profile", PROFILE, "--json", *args]),
            opts=RunCommandOpts(timeout=timedelta(seconds=30)),
        )
        if result.error or result.exit_code not in {None, 0}:
            # The CLI can return a useful structured error with a nonzero exit code.
            value = payload(result)
            if value.get("success") is not False:
                raise ServiceError("The browser command failed.")
            return value
        return payload(result)

    async def prepare(self, owner):
        sandbox = await self.boxes.get(owner, "persistent-browser")
        key = (owner, sandbox.id)
        if key in self.ready:
            return sandbox
        result = await sandbox.commands.run("mkdir -p /tmp/theos-browser")
        if result.error:
            raise ServiceError("The browser could not be prepared.")
        await sandbox.files.write_file(
            "/tmp/theos-browser/profile.py", Path(__file__).with_name("profile.py").read_text()
        )
        # Do not overwrite a live profile when reconnecting after an application restart.
        result = await sandbox.commands.run("test -d /tmp/theos-browser/profile")
        restored_profile = False
        if result.exit_code != 0:
            row = self.runtime.db.one(
                "SELECT encrypted FROM credentials WHERE owner=? AND service='browser'", (owner,)
            )
            if row:
                archive = self.encryption().decrypt(row["encrypted"].encode())
                await sandbox.files.write_file(ARCHIVE, archive)
                restored = await sandbox.commands.run(
                    "python /tmp/theos-browser/profile.py restore"
                )
                if restored.error or restored.exit_code not in {None, 0}:
                    raise ServiceError("The saved browser profile could not be restored.")
                restored_profile = True
        opened = await self.cli(sandbox, ["get", "url"])
        if not opened.get("success"):
            raise ServiceError("The browser could not be started.")
        if restored_profile:
            loaded = await self.cli(sandbox, ["state", "load", PROFILE + "/.theos-auth.json"])
            if not loaded.get("success"):
                raise ServiceError("The saved browser login could not be restored.")
        self.ready = {entry for entry in self.ready if entry[0] != owner}
        self.ready.add(key)
        return sandbox

    async def select(self, sandbox, session):
        label = "theos-" + hashlib.sha256(session.encode()).hexdigest()[:24]
        selected = await self.cli(sandbox, ["tab", label])
        if not selected.get("success"):
            selected = await self.cli(sandbox, ["tab", "new", "--label", label, "about:blank"])
        if not selected.get("success"):
            raise ServiceError("The conversation browser tab is unavailable.")

    async def save(self, owner, sandbox):
        # Cookies and localStorage can remain in Chromium memory before disk flush.
        # Capture their live state alongside the profile's IndexedDB and other files.
        state = await self.cli(sandbox, ["state", "save", PROFILE + "/.theos-auth.json"])
        if not state.get("success"):
            raise ServiceError("The browser login state could not be saved.")
        result = await sandbox.commands.run("python /tmp/theos-browser/profile.py snapshot")
        if result.error or result.exit_code not in {None, 0}:
            raise ServiceError("The browser recovery state could not be saved.")
        archive = await sandbox.files.read_bytes(
            ARCHIVE, range_header=f"bytes=0-{MAX_PROFILE_BYTES}"
        )
        if len(archive) > MAX_PROFILE_BYTES:
            raise ValueError("The browser profile exceeds its size limit.")
        self.runtime.db.execute(
            "INSERT INTO credentials VALUES (?,?,?,?) ON CONFLICT(owner,service) DO UPDATE SET "
            "encrypted=excluded.encrypted,updated=excluded.updated",
            (owner, "browser", self.encryption().encrypt(archive).decode(), time.time()),
        )

    async def execute(self, owner, session, args, workspace=None):
        """Serialize browser actions. Never replay a command after a lost response."""
        while args and args[0] == "--json":
            args = args[1:]
        if not args or args[0] not in ACTIONS:
            raise ValueError(
                "Use a standalone browser navigation, inspection, or interaction command."
            )
        if any(arg.split("=", 1)[0] in FORBIDDEN_FLAGS for arg in args):
            raise ValueError("Browser profiles, connections, and tabs are managed automatically.")
        async with self.locks.setdefault(owner, asyncio.Lock()):
            sandbox = await self.prepare(owner)
            await self.select(sandbox, session)
            args = list(args)
            destination = None
            output_index = 2 if args[0] == "download" else 1
            if args[0] in {"screenshot", "pdf", "download"}:
                if len(args) <= output_index or args[output_index].startswith("-"):
                    raise ValueError("Supply an output path inside /workspace.")
                destination = self.boxes.workspace_path(args[output_index])
                args[output_index] = "/tmp/theos-browser/output" + Path(destination).suffix
            if args[0] == "upload":
                if workspace is None or len(args) != 3:
                    raise ValueError("Supply an element and one workspace file to upload.")
                source = self.boxes.workspace_path(args[2])
                data = await self.boxes.read_bytes(workspace, source)
                args[2] = "/tmp/theos-browser/upload" + Path(source).suffix
                await sandbox.files.write_file(args[2], data)
            result = None
            try:
                result = await self.cli(sandbox, args)
                if destination and result.get("success") and workspace is not None:
                    data = await self.boxes.read_bytes(sandbox, args[output_index])
                    parent = str(Path(destination).parent)
                    await workspace.commands.run("mkdir -p " + shlex.quote(parent))
                    await workspace.files.write_file(destination, data)
                    result["data"] = {"path": destination}
                return result
            finally:
                try:
                    await self.save(owner, sandbox)
                except Exception as error:
                    logger.warning(
                        "browser_profile_save_failed", extra={"error_type": type(error).__name__}
                    )
                    if result is None:
                        raise OutcomeUnknown(
                            "The browser action outcome is unknown. Do not repeat it automatically."
                        ) from error

    async def disconnect(self, owner):
        async with self.locks.setdefault(owner, asyncio.Lock()):
            await self.boxes.destroy(owner, "persistent-browser")
            self.ready = {key for key in self.ready if key[0] != owner}
            self.runtime.db.execute(
                "DELETE FROM credentials WHERE owner=? AND service='browser'", (owner,)
            )

    async def close(self):
        await self.boxes.close()
