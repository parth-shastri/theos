"""Remote OpenSandbox execution with per-conversation lifecycle state."""

from datetime import timedelta

from theos.services.errors import ServiceError


class Sandboxes:
    """Never mount the application filesystem or pass application credentials."""

    def __init__(self, settings, db, files):
        self.settings = settings
        self.db = db
        self.files = files
        self.clients = {}

    async def get(self, owner, session_id):
        """Reconnect the conversation sandbox or create its first instance."""
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
        from opensandbox.exceptions import SandboxException

        key = (owner, session_id)
        if key in self.clients:
            return self.clients[key]
        config = self.settings.sandbox
        connection = ConnectionConfig(
            domain=config.domain,
            api_key=config.api_key.get_secret_value() or None,
            use_server_proxy=config.use_server_proxy,
            request_timeout=timedelta(seconds=30),
        )
        try:
            saved = self.db.record(owner, "sandbox", session_id)
        except LookupError:
            saved = None
        if saved:
            try:
                sandbox = await Sandbox.connect(saved["sandbox_id"], connection_config=connection)
            except SandboxException as error:
                if getattr(error, "status_code", None) not in {404, 410}:
                    raise ServiceError(
                        "The saved sandbox is unavailable. Retry its connection before restoring work."
                    ) from error
                # A confirmed expired sandbox can be recreated from saved workspace objects.
                saved = None
        if not saved:
            sandbox = await Sandbox.create(
                config.image,
                # The SDK default keeps the container alive without starting the interpreter.
                entrypoint=["/opt/code-interpreter/code-interpreter.sh"],
                timeout=timedelta(seconds=config.timeout_seconds),
                connection_config=connection,
                env={},
                resource={"cpu": "1", "memory": "512Mi"},
            )
            self.db.put_record(owner, "sandbox", session_id, {"sandbox_id": sandbox.id})
        self.clients[key] = sandbox
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
