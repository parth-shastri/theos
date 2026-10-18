"""Remote OpenSandbox execution with per-conversation lifecycle state."""

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta

from theos.services.errors import ServiceError

from .errors import WorkspaceUnavailable


class Sandboxes:
    """Never mount the application filesystem or pass application credentials."""

    TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, settings, db, files):
        self.settings = settings
        self.db = db
        self.files = files
        self.clients = {}
        self.locks = {}

    async def stage_result(self, owner, session_id, name, content):
        """Write one normalized provider result outside the durable task workspace."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("Use a simple provider tool name for a staged result.")

        data = content.encode("utf-8")
        digest = hashlib.sha256(name.encode() + b"\0" + data).hexdigest()[:20]
        path = f"/tmp/theos-results/{name}-{digest}.json"
        sandbox = await self.get(owner, session_id)

        # /tmp is outside /workspace, which is the only directory checkpointed to R2.
        result = await sandbox.commands.run("mkdir -p /tmp/theos-results")
        if getattr(result, "error", None):
            raise RuntimeError("The temporary result directory could not be prepared.")
        await sandbox.files.write_file(path, data)
        return {"path": path, "size_bytes": len(data)}

    async def forget(self, owner, session_id):
        """Close only the local connection and remove its saved reference."""
        old = self.clients.pop((owner, session_id), None)
        if old:
            await old.close()
        try:
            return self.db.delete_record(owner, "sandbox", session_id)
        except LookupError:
            return {"deleted": session_id}

    async def destroy(self, owner, session_id):
        """Destroy an existing sandbox without creating one just to destroy it."""
        from opensandbox import Sandbox
        from opensandbox.exceptions import SandboxException

        try:
            saved = self.db.record(owner, "sandbox", session_id)
        except LookupError:
            saved = None
        sandbox = self.clients.get((owner, session_id))
        try:
            if sandbox is None and saved:
                sandbox = await Sandbox.connect(
                    saved["sandbox_id"], connection_config=self.connection()
                )
            if sandbox:
                await sandbox.kill()
        except SandboxException as error:
            if getattr(error, "status_code", None) not in {404, 410}:
                raise ServiceError(
                    "The workspace could not be cleared. Its saved connection remains."
                ) from error
        finally:
            if sandbox and (owner, session_id) not in self.clients:
                await sandbox.close()
        return await self.forget(owner, session_id)

    def connection(self):
        from opensandbox.config import ConnectionConfig

        config = self.settings.sandbox
        return ConnectionConfig(
            domain=config.domain,
            api_key=config.api_key.get_secret_value() or None,
            use_server_proxy=config.use_server_proxy,
            request_timeout=timedelta(seconds=30),
        )

    def remember(self, owner, session_id, sandbox, info, saved=None):
        """Keep one creation deadline across reconnects and status checks."""
        saved = saved or {}
        created = saved.get("created_at") or getattr(info, "created_at", None) or datetime.now(UTC)
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        deadline = created + timedelta(seconds=self.settings.sandbox.timeout_seconds)
        remote_expiry = getattr(info, "expires_at", None)
        if remote_expiry:
            deadline = min(deadline, remote_expiry)
        self.db.put_record(
            owner,
            "sandbox",
            session_id,
            {
                "sandbox_id": sandbox.id,
                "created_at": created.isoformat(),
                "expires_at": deadline.isoformat(),
            },
        )
        return deadline

    async def get(self, owner, session_id):
        """Check cached state and replace only confirmed expired or missing instances."""
        import httpx
        from opensandbox.exceptions import SandboxException, SandboxReadyTimeoutException

        lock = self.locks.setdefault((owner, session_id), asyncio.Lock())
        async with lock:
            try:
                return await self._get(owner, session_id)
            except WorkspaceUnavailable:
                raise
            except (httpx.RequestError, TimeoutError) as error:
                raise WorkspaceUnavailable(
                    "The workspace is temporarily unavailable. Saved files remain available. "
                    "The runtime will try to reconnect on the next workspace operation."
                ) from error
            except SandboxReadyTimeoutException as error:
                raise WorkspaceUnavailable(
                    "The workspace did not become ready. Saved files remain available. "
                    "The runtime will try again on the next workspace operation."
                ) from error
            except SandboxException as error:
                if getattr(error, "status_code", None) in self.TRANSIENT_STATUS_CODES:
                    raise WorkspaceUnavailable(
                        "The workspace is temporarily unavailable. Saved files remain available. "
                        "The runtime will try to reconnect on the next workspace operation."
                    ) from error
                raise

    async def _get(self, owner, session_id):
        from opensandbox import Sandbox
        from opensandbox.exceptions import SandboxException

        key = (owner, session_id)
        try:
            saved = self.db.record(owner, "sandbox", session_id)
        except LookupError:
            saved = None
        sandbox = self.clients.get(key)
        if saved or sandbox:
            try:
                if sandbox is None:
                    sandbox = await Sandbox.connect(
                        saved["sandbox_id"], connection_config=self.connection()
                    )
                info = await sandbox.get_info()
                deadline = self.remember(owner, session_id, sandbox, info, saved)
                state = getattr(getattr(info, "status", None), "state", "")
                if datetime.now(UTC) >= deadline or state in {"Terminated", "Failed", "Expired"}:
                    # Expiry checks happen before execution. Never replay a failed command.
                    await sandbox.kill()
                    if key not in self.clients:
                        await sandbox.close()
                    await self.forget(owner, session_id)
                else:
                    self.clients[key] = sandbox
                    return sandbox
            except SandboxException as error:
                status_code = getattr(error, "status_code", None)
                if status_code not in {404, 410}:
                    if sandbox and key not in self.clients:
                        await sandbox.close()
                    if status_code in self.TRANSIENT_STATUS_CODES:
                        raise WorkspaceUnavailable(
                            "The workspace is temporarily unavailable. Saved files remain available. "
                            "The runtime will try to reconnect on the next workspace operation."
                        ) from error
                    raise ServiceError(
                        "The workspace request failed. Its saved connection remains available."
                    ) from error
                if sandbox and key not in self.clients:
                    await sandbox.close()
                await self.forget(owner, session_id)
        sandbox = await Sandbox.create(
            self.settings.sandbox.image,
            entrypoint=["/opt/code-interpreter/code-interpreter.sh"],
            timeout=timedelta(seconds=self.settings.sandbox.timeout_seconds),
            connection_config=self.connection(),
            env={},
            resource={"cpu": "1", "memory": "512Mi"},
        )
        # Save the ID before further remote reads so a metadata failure cannot orphan it.
        self.db.put_record(owner, "sandbox", session_id, {"sandbox_id": sandbox.id})
        self.clients[key] = sandbox
        self.remember(owner, session_id, sandbox, await sandbox.get_info())
        return sandbox

    async def close(self):
        """Close local SDK clients without destroying the remote sandboxes."""
        for sandbox in self.clients.values():
            await sandbox.close()
        self.clients.clear()

    def tools(self, owner, session_id):
        """Build the service tools for the authenticated owner."""
        from .tools import sandbox_tools

        return sandbox_tools(self, owner, session_id)
