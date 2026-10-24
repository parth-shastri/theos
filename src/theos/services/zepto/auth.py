"""Zepto OAuth, Telegram return handoff, and encrypted credential storage."""

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.auth.exceptions import OAuthFlowError, OAuthRegistrationError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_registration_request,
    create_oauth_metadata_request,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    handle_registration_response,
)
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from theos.services.errors import ServiceError
from theos.services.zepto.session import ZeptoSession
from theos.storage.account_access import account_access, browser_account_access

logger = logging.getLogger("theos")
CLIENT_KEY = "zepto_oauth_client"
CALLBACK_TIMEOUT = 600


@dataclass
class PendingConnection:
    """Hold one short-lived account authorization for one private owner."""

    owner: str
    redirect_uri: str
    callback: asyncio.Future
    send_link: Callable[[str], Awaitable[None]]
    send_status: Callable[[str], Awaitable[None]]
    created: float
    state: str | None = None
    task: asyncio.Task | None = None
    failed: bool = False
    verified: bool = False
    cancelled: bool = False
    authorization_url: str | None = None
    staged_credentials: str | None = None


class ZeptoTokenStorage(TokenStorage):
    """Keep one OAuth client's registration and each owner's tokens encrypted."""

    def __init__(self, settings, db, owner, pending=None):
        self.settings = settings
        self.db = db
        self.owner = owner
        self.pending = pending
        key = settings.token_encryption_key.get_secret_value()
        self.cipher = Fernet(key.encode()) if key else None

    def _encrypt(self, value):
        if self.cipher is None:
            raise ServiceError("Zepto credential encryption is not configured.")
        return self.cipher.encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()

    def _decrypt(self, value):
        if self.cipher is None:
            raise ServiceError("Zepto credential encryption is not configured.")
        try:
            return json.loads(self.cipher.decrypt(value.encode()))
        except (InvalidToken, ValueError, TypeError) as error:
            raise ServiceError(
                "The saved Zepto credential cannot be decrypted. Restore the encryption key or reconnect."
            ) from error

    def _read_owner(self):
        if self.pending is not None:
            return (
                self._decrypt(self.pending.staged_credentials)
                if self.pending.staged_credentials
                else {}
            )
        row = self.db.one(
            "SELECT encrypted FROM credentials WHERE owner=? AND service='zepto'", (self.owner,)
        )
        return self._decrypt(row["encrypted"]) if row else {}

    def _write_owner(self, value):
        encrypted = self._encrypt(value)
        if self.pending is not None:
            self.pending.staged_credentials = encrypted
            return
        self.db.ensure_user(self.owner)
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO credentials VALUES (?, 'zepto', ?, ?) "
                "ON CONFLICT(owner,service) DO UPDATE SET encrypted=excluded.encrypted, "
                "updated=excluded.updated",
                (self.owner, encrypted, time.time()),
            )

    async def get_tokens(self):
        payload = self._read_owner().get("tokens")
        return OAuthToken.model_validate(payload) if payload else None

    async def set_tokens(self, tokens):
        if not account_access(self.settings, self.db, self.owner):
            raise PermissionError("This user no longer has account access.")
        payload = self._read_owner()
        payload["tokens"] = tokens.model_dump(mode="json")
        payload["endpoint"] = self.settings.zepto_url
        payload["expires_at"] = (
            time.time() + tokens.expires_in if tokens.expires_in is not None else None
        )
        self._write_owner(payload)

    async def get_expiry(self):
        return self._read_owner().get("expires_at")

    async def get_client_info(self):
        row = self.db.one("SELECT value FROM application_state WHERE key=?", (CLIENT_KEY,))
        if not row:
            return None
        payload = self._decrypt(row["value"])
        if (
            payload.get("redirect_uri") != self.settings.zepto_redirect_uri
            or payload.get("endpoint") != self.settings.zepto_url
        ):
            return None
        return OAuthClientInformationFull.model_validate(payload["client_info"])

    async def set_client_info(self, client_info):
        payload = {
            "redirect_uri": self.settings.zepto_redirect_uri,
            "endpoint": self.settings.zepto_url,
            "client_info": client_info.model_dump(mode="json"),
        }
        encrypted = self._encrypt(payload)
        self.db.execute(
            "INSERT OR REPLACE INTO application_state VALUES (?, ?)", (CLIENT_KEY, encrypted)
        )


class DurableOAuthClientProvider(OAuthClientProvider):
    """Restore the saved expiry time so the SDK refreshes tokens after a restart."""

    async def _initialize(self):
        await super()._initialize()
        if self.context.current_tokens:
            self.context.token_expiry_time = await self.context.storage.get_expiry()


class Zepto:
    """Manage per-owner Zepto OAuth and remote MCP calls."""

    def __init__(self, settings, db, http):
        self.settings = settings
        self.db = db
        self.http = http
        self.pending: dict[str, PendingConnection] = {}
        self.pending_by_state: dict[str, PendingConnection] = {}
        self.browser_status: dict[str, dict] = {}
        self.sessions: dict[str, ZeptoSession] = {}
        self.registration_lock = asyncio.Lock()
        self.closed = False

    def enabled(self):
        return bool(self.settings.zepto_url)

    def connected(self, owner):
        flow = self.pending.get(owner)
        if flow and not flow.verified:
            return False
        return self._credentials_present(owner)

    def _credentials_present(self, owner):
        try:
            return (
                ZeptoTokenStorage(self.settings, self.db, owner)._read_owner().get("endpoint")
                == self.settings.zepto_url
                and self.db.one(
                    "SELECT 1 FROM credentials WHERE owner=? AND service='zepto'", (owner,)
                )
                is not None
            )
        except ServiceError:
            return False

    def authorize(self, owner, *, require_enabled=True):
        if require_enabled and not self.enabled():
            raise ServiceError("Zepto is not configured for this installation.")
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("Connect Zepto from an authorized private workspace.")

    def connection_status(self, owner):
        """Return setup progress only to its authenticated browser owner."""
        if not browser_account_access(self.settings, owner, self.db):
            raise PermissionError("Browser account access is required.")
        flow = self.pending.get(owner)
        if flow and not flow.verified and not flow.failed:
            if time.time() - flow.created > CALLBACK_TIMEOUT:
                return {"status": "expired", "message": "Zepto sign-in expired. Connect again."}
            if flow.authorization_url:
                return {
                    "status": "waiting",
                    "url": flow.authorization_url,
                    "manual_return": not flow.redirect_uri.startswith("https://"),
                }
        if owner in self.browser_status:
            return self.browser_status[owner]
        try:
            saved = self.db.record(owner, "account_connections", "zepto")
        except LookupError:
            return {"status": "starting" if flow else "idle"}
        if not flow and saved["status"] in {"starting", "waiting"}:
            return {"status": "failed", "message": "Zepto setup was interrupted. Connect again."}
        return {key: saved[key] for key in ("status", "message")}

    def _status(self, owner, status, message):
        self.browser_status[owner] = {"status": status, "message": message}
        self.db.put_record(owner, "account_connections", "zepto", self.browser_status[owner])

    def _discard_credentials(self, flow):
        if not flow.verified:
            flow.staged_credentials = None

    async def connect_from_browser(self, owner):
        """Publish a sign-in link without putting OAuth data in chat history."""
        if not browser_account_access(self.settings, owner, self.db):
            raise PermissionError("Browser account access is required.")
        self.authorize(owner)
        current = self.pending.get(owner)
        if current and current.task and not current.task.done():
            if time.time() - current.created <= CALLBACK_TIMEOUT:
                return self.connection_status(owner)
            await self.cancel(owner)
        self.browser_status[owner] = {"status": "starting"}

        async def send_link(url):
            self.browser_status[owner] = {
                "status": "waiting",
                "url": url,
                "manual_return": not self.settings.zepto_redirect_uri.startswith("https://"),
            }

        async def send_status(message):
            flow = self.pending.get(owner)
            if flow and not flow.failed and self._credentials_present(owner):
                flow.verified = True
            self._status(
                owner,
                "connected"
                if self.connected(owner) and not (flow and flow.failed)
                else "cancelled"
                if flow and flow.cancelled
                else "failed",
                message,
            )

        await self.connect(owner, send_link, send_status)
        return self.connection_status(owner)

    def _client_metadata(self, scopes=None):
        return OAuthClientMetadata(
            redirect_uris=[self.settings.zepto_redirect_uri],
            token_endpoint_auth_method="none",
            client_name=self.settings.name,
            scope=" ".join(scopes or []) or None,
        )

    async def _protected_resource_metadata(self):
        for url in build_protected_resource_metadata_discovery_urls(None, self.settings.zepto_url):
            response = await self.http.send(create_oauth_metadata_request(url))
            metadata = await handle_protected_resource_response(response)
            if metadata:
                return metadata
        raise OAuthFlowError("Zepto did not return protected resource metadata.")

    async def _authorization_metadata(self, auth_server):
        for url in build_oauth_authorization_server_metadata_discovery_urls(
            auth_server, self.settings.zepto_url
        ):
            response = await self.http.send(create_oauth_metadata_request(url))
            ok, metadata = await handle_auth_metadata_response(response)
            if not ok:
                break
            if metadata:
                return metadata
        raise OAuthFlowError("Zepto did not return authorization server metadata.")

    async def _ensure_client_info(self):
        async with self.registration_lock:
            store = ZeptoTokenStorage(self.settings, self.db, "telegram:registration")
            if await store.get_client_info():
                return
            try:
                resource = await self._protected_resource_metadata()
                if not resource.authorization_servers:
                    raise OAuthFlowError("Zepto did not identify an authorization server.")
                auth_server = str(resource.authorization_servers[0])
                metadata = await self._authorization_metadata(auth_server)
                registration = create_client_registration_request(
                    metadata,
                    self._client_metadata(resource.scopes_supported),
                    f"{urlsplit(auth_server).scheme}://{urlsplit(auth_server).netloc}",
                )
                response = await self.http.send(registration)
                client_info = await handle_registration_response(response)
                await store.set_client_info(client_info)
            except (httpx.HTTPError, OAuthRegistrationError, OAuthFlowError) as error:
                raise ServiceError(
                    "Zepto OAuth setup failed. Check the configured MCP endpoint."
                ) from error

    def _provider(self, owner, flow=None):
        store = ZeptoTokenStorage(self.settings, self.db, owner, pending=flow)

        async def redirect(url):
            state = parse_qs(urlsplit(url).query).get("state", [None])[0]
            if not state:
                raise OAuthFlowError("Zepto did not return an OAuth state.")
            flow.state = state
            self.pending_by_state[state] = flow
            flow.authorization_url = url
            self._status(owner, "waiting", "Finish Zepto sign-in in the opened browser tab.")
            await flow.send_link(url)

        async def callback():
            if flow is None:
                raise OAuthFlowError("Reconnect Zepto from your private workspace.")
            try:
                return await asyncio.wait_for(flow.callback, CALLBACK_TIMEOUT)
            except TimeoutError as error:
                raise OAuthFlowError("Zepto setup expired.") from error

        return DurableOAuthClientProvider(
            self.settings.zepto_url,
            self._client_metadata(),
            store,
            redirect_handler=redirect if flow else None,
            callback_handler=callback if flow else None,
        )

    async def connect(self, owner, send_link, send_status):
        """Start an OAuth task and return while the user completes browser sign-in."""
        self.authorize(owner)
        if self.closed:
            raise ServiceError("Zepto setup is stopping. Try again after the application starts.")
        current = self.pending.get(owner)
        if current and current.task and not current.task.done():
            await send_status("Zepto setup is already waiting for your sign-in.")
            return
        await self._close_session(owner)
        flow = PendingConnection(
            owner=owner,
            redirect_uri=self.settings.zepto_redirect_uri,
            callback=asyncio.get_running_loop().create_future(),
            send_link=send_link,
            send_status=send_status,
            created=time.time(),
        )
        self.pending[owner] = flow
        self._status(owner, "starting", "Preparing your private Zepto sign-in link.")
        flow.task = asyncio.create_task(self._connect(flow))

    async def _connect(self, flow):
        try:
            await self._ensure_client_info()
            provider = self._provider(flow.owner, flow)
            async with httpx.AsyncClient(timeout=30, auth=provider) as http:
                async with streamable_http_client(self.settings.zepto_url, http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
            if not account_access(self.settings, self.db, flow.owner):
                raise PermissionError("This user no longer has account access.")
            staged = ZeptoTokenStorage(
                self.settings, self.db, flow.owner, pending=flow
            )._read_owner()
            if not staged.get("tokens"):
                raise ServiceError("Zepto did not complete account authorization. Connect again.")
            ZeptoTokenStorage(self.settings, self.db, flow.owner)._write_owner(staged)
            flow.verified = True
            self._status(
                flow.owner,
                "connected",
                "Zepto is connected. Choose a delivery address before shopping.",
            )
            try:
                await flow.send_status(f"Zepto is connected. I found {len(listed.tools)} tools.")
            except Exception as error:
                logger.warning(
                    "zepto_connection_notification_failed",
                    extra={"error_type": type(error).__name__},
                )
        except asyncio.CancelledError:
            self._discard_credentials(flow)
            self._status(flow.owner, "cancelled", "Zepto setup stopped. You can connect again.")
            raise
        except Exception as error:
            flow.failed = True
            self._discard_credentials(flow)
            self._status(
                flow.owner,
                "cancelled" if flow.cancelled else "failed",
                "Zepto sign-in was cancelled. Connect again when ready."
                if flow.cancelled
                else "Zepto could not connect. Check authorization and connect again.",
            )
            logger.warning("zepto_connect_failed", extra={"error_type": type(error).__name__})
            await flow.send_status(
                "Zepto could not connect. Check the account authorization and connect again."
            )
        finally:
            if self.pending.get(flow.owner) is flow:
                self.pending.pop(flow.owner, None)
            if flow.state:
                self.pending_by_state.pop(flow.state, None)

    def _validate_return(self, flow, state):
        if time.time() - flow.created > CALLBACK_TIMEOUT:
            raise ValueError("This Zepto link expired. Connect Zepto again.")
        if not flow.state or not secrets.compare_digest(state, flow.state):
            raise ValueError("This Zepto return link does not match the pending setup.")
        if flow.callback.done():
            raise ValueError("This Zepto return link is empty or already used.")

    def _resolve(self, flow, code, state):
        self._validate_return(flow, state)
        if not code:
            raise ValueError("The Zepto return link has no authorization code. Connect again.")
        flow.callback.set_result((code, state))

    def _reject(self, flow, state):
        self._validate_return(flow, state)
        flow.cancelled = True
        flow.callback.set_exception(OAuthFlowError("Zepto sign-in was cancelled."))
        raise ValueError("Zepto sign-in was cancelled. Connect again when ready.")

    async def finish_from_telegram(self, owner, return_url):
        """Pass a localhost redirect back to the pending OAuth client."""
        if not owner.startswith("telegram:"):
            raise PermissionError("Private Telegram account access is required.")
        await self.finish_return_url(owner, return_url)

    async def finish_return_url(self, owner, return_url):
        """Require the same owner and one-use state for a pasted return URL."""
        self.authorize(owner)
        flow = self.pending.get(owner)
        if not flow:
            raise ValueError("No Zepto setup is waiting. Connect Zepto again.")
        expected = urlsplit(flow.redirect_uri)
        actual = urlsplit(return_url)
        if expected.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError(
                "This setup uses a direct callback. Return to your workspace after sign-in."
            )
        if (actual.scheme, actual.netloc, actual.path) != (
            expected.scheme,
            expected.netloc,
            expected.path,
        ):
            raise ValueError("Send the full Zepto return URL from the browser address bar.")
        query = parse_qs(actual.query, max_num_fields=20)
        state = query.get("state", [""])[0]
        code = query.get("code", [""])[0]
        error = query.get("error", [""])[0]
        if error:
            self._reject(flow, state)
        self._resolve(flow, code, state)

    async def finish_from_browser(self, state, code, error=""):
        """Accept a direct HTTPS callback for a pending owner-bound flow."""
        if not self.settings.zepto_redirect_uri.startswith("https://"):
            raise ValueError("The Zepto callback route is disabled for this installation.")
        flow = self.pending_by_state.get(state)
        if not flow:
            raise ValueError("This Zepto link expired. Connect Zepto again.")
        self.authorize(flow.owner)
        if error:
            self._reject(flow, state)
        self._resolve(flow, code, state)

    async def cancel(self, owner):
        """Cancel setup and preserve the account that was connected before it."""
        self.authorize(owner, require_enabled=False)
        flow = self.pending.get(owner)
        if flow and flow.task and not flow.task.done():
            flow.task.cancel()
            await asyncio.gather(flow.task, return_exceptions=True)
            self._discard_credentials(flow)
            if self.pending.get(owner) is flow:
                self.pending.pop(owner, None)
            if flow.state:
                self.pending_by_state.pop(flow.state, None)
        self._status(owner, "cancelled", "Zepto setup cancelled. You can connect later.")

    async def disconnect(self, owner):
        """Remove one owner's local Zepto credentials and cancel pending setup."""
        self.authorize(owner, require_enabled=False)
        await self._close_session(owner)
        flow = self.pending.get(owner)
        if flow and flow.task and not flow.task.done():
            flow.task.cancel()
            await asyncio.gather(flow.task, return_exceptions=True)
        with self.db.transaction():
            self.db.execute("DELETE FROM credentials WHERE owner=? AND service='zepto'", (owner,))
        self.browser_status.pop(owner, None)
        self.db.put_record(
            owner,
            "account_connections",
            "zepto",
            {"status": "idle", "message": "Zepto disconnected."},
        )
        return True

    async def _remote(self, owner, name=None, arguments=None):
        self.authorize(owner)
        if self.closed:
            raise ServiceError("Zepto is stopping. Try again after the application starts.")
        session = self.sessions.get(owner)
        if session is None or session.task.done():
            session = ZeptoSession(self.settings.zepto_url, self._provider(owner))
            self.sessions[owner] = session
        return await session.request(name, arguments)

    async def _close_session(self, owner):
        session = self.sessions.pop(owner, None)
        if session is not None:
            await session.close()

    async def close(self):
        """Cancel pending browser handoffs before the database closes."""
        self.closed = True
        tasks = [flow.task for flow in self.pending.values() if flow.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        sessions = list(self.sessions.values())
        self.sessions.clear()
        await asyncio.gather(*(session.close() for session in sessions))


def prepare_telegram_update(settings, update):
    """Encrypt pasted authorization URLs before the Telegram inbox saves them."""
    result = deepcopy(update)
    message = result.get("message", {})
    text = message.get("text", "")
    command, separator, value = text.partition(" ")
    is_finish_command = command.split("@")[0] == "/zepto_finish"
    if not (is_finish_command and separator):
        try:
            parts = urlsplit(text.strip())
            query = parse_qs(parts.query, max_num_fields=20)
        except ValueError:
            return result
        if not (
            parts.scheme == "http"
            and parts.hostname in {"localhost", "127.0.0.1"}
            and parts.path == "/callback"
            and query.get("code")
            and query.get("state")
        ):
            return result
        value = text
    message["text"] = "/zepto_finish"
    if len(value) > 4000:
        message["_theos_zepto_return_invalid"] = True
        return result
    key = settings.token_encryption_key.get_secret_value()
    if not key:
        message["_theos_zepto_return_invalid"] = True
        return result
    cipher = Fernet(key.encode())
    message["_theos_zepto_return"] = cipher.encrypt(value.strip().encode()).decode()
    return result
