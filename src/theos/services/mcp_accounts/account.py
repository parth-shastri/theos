"""Owner-bound OAuth and encrypted credentials for official MCP servers."""

import asyncio
import base64
import hashlib
import json
import math
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from theos.services.errors import ServiceError
from theos.storage.account_access import account_access

from .session import AccountSession


@dataclass(frozen=True)
class AccountSpec:
    name: str
    label: str
    endpoint: str
    authorization_url: str
    token_url: str
    read_tools: frozenset[str]
    scopes: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    methods: dict[str, frozenset[str]] = field(default_factory=dict)
    scope_separator: str = " "
    token_basic_auth: bool = False


class MCPAccount:
    """Use provider tools directly while Theos owns access and durable execution."""

    def __init__(self, settings, config, spec, db, http):
        config.check_callback(spec.name)
        self.settings, self.config, self.spec = settings, config, spec
        self.db, self.http = db, http
        key = settings.token_encryption_key.get_secret_value()
        self.cipher = Fernet(key.encode()) if key else None
        self.locks, self.sessions = {}, {}
        self.closed = False

    def authorize(self, owner):
        if self.closed or not self.config.enabled or self.cipher is None:
            raise ServiceError(f"{self.spec.label} is disabled or stopping.")
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("Connect this account from an authorized private workspace.")

    def lock(self, owner):
        return self.locks.setdefault(owner, asyncio.Lock())

    @property
    def scopes(self):
        return self.spec.scopes if self.config.scopes is None else tuple(self.config.scopes)

    def fingerprint(self):
        value = [
            self.spec.endpoint,
            self.spec.authorization_url,
            self.spec.token_url,
            self.config.client_id,
            self.config.client_secret.get_secret_value(),
            self.config.redirect_uri,
            self.scopes,
        ]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def encode(self, value):
        if self.cipher is None:
            raise ServiceError("Account credential encryption is not configured.")
        return self.cipher.encrypt(json.dumps(value).encode()).decode()

    def decode(self, encrypted):
        try:
            if self.cipher is None:
                raise ValueError("Missing cipher")
            payload = json.loads(self.cipher.decrypt(encrypted.encode()))
            if not isinstance(payload, dict) or payload.get("config") != self.fingerprint():
                raise ValueError("Account configuration changed")
            return payload
        except (InvalidToken, ValueError, TypeError) as error:
            raise ServiceError("The saved account is unavailable. Connect it again.") from error

    def read(self, owner):
        row = self.db.one(
            "SELECT encrypted FROM credentials WHERE owner=? AND service=?",
            (owner, self.spec.name),
        )
        if not row:
            raise ServiceError("Connect this account from Connections first.")
        return self.decode(row["encrypted"])

    def save(self, owner, payload):
        self.authorize(owner)
        self.db.ensure_user(owner)
        payload = {**payload, "config": self.fingerprint()}
        self.db.execute(
            "INSERT INTO credentials VALUES (?,?,?,?) ON CONFLICT(owner,service) DO UPDATE SET "
            "encrypted=excluded.encrypted,updated=excluded.updated",
            (owner, self.spec.name, self.encode(payload), time.time()),
        )

    def connected(self, owner):
        try:
            self.authorize(owner)
            payload = self.read(owner)
            return bool(payload.get("access_token")) and (
                payload.get("expires_at") is None
                or payload["expires_at"] > time.time()
                or bool(payload.get("refresh_token"))
            )
        except (ServiceError, PermissionError):
            return False

    def status(self, owner):
        waiting = self.db.one(
            "SELECT 1 FROM oauth_states WHERE owner=? AND service=? AND expires>?",
            (owner, self.spec.name, time.time()),
        )
        return {
            "id": self.spec.name,
            "name": self.spec.label,
            "configured": self.config.enabled,
            "connected": self.connected(owner),
            "setup": {"status": "waiting" if waiting else "idle"},
        }

    async def start(self, owner):
        self.authorize(owner)
        async with self.lock(owner):
            self.db.ensure_user(owner)
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            with self.db.transaction():
                self.db.execute(
                    "DELETE FROM oauth_states WHERE owner=? AND service=?", (owner, self.spec.name)
                )
                self.db.execute(
                    "INSERT INTO oauth_states VALUES (?,?,?,?,?)",
                    (
                        hashlib.sha256(state.encode()).hexdigest(),
                        owner,
                        self.spec.name,
                        self.encode({"verifier": verifier, "config": self.fingerprint()}),
                        time.time() + 600,
                    ),
                )
            params = {
                "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri,
                "state": state,
                "response_type": "code",
                "code_challenge": challenge.decode().rstrip("="),
                "code_challenge_method": "S256",
            }
            if self.scopes:
                params["scope"] = self.spec.scope_separator.join(self.scopes)
            return {
                "status": "waiting",
                "url": self.spec.authorization_url + "?" + urlencode(params),
            }

    async def token_request(self, form, *, refresh=False):
        data = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            **form,
        }
        kwargs = {}
        secret = self.config.client_secret.get_secret_value()
        if self.spec.token_basic_auth:
            data.pop("client_id")
            kwargs["auth"] = httpx.BasicAuth(self.config.client_id, secret)
        else:
            data["client_secret"] = secret
        try:
            response = await self.http.post(
                self.spec.token_url,
                data=data,
                headers={"Accept": "application/json"},
                follow_redirects=False,
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is False or payload.get("error"):
                raise ValueError("Rejected token request")
            token = payload.get("access_token")
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError("Missing access token")
            # Slack returns a user-token type rather than the OAuth bearer label.
            if str(payload.get("token_type", "bearer")).lower() not in {"bearer", "user"}:
                raise ValueError("Unsupported token type")
            if "refresh_token" in payload and (
                not isinstance(payload["refresh_token"], str) or not payload["refresh_token"]
            ):
                raise ValueError("Invalid refresh token")
            expires = payload.get("expires_in")
            if expires is not None:
                seconds = float(expires)
                if not math.isfinite(seconds) or seconds <= 0:
                    raise ValueError("Invalid token expiry")
                payload["expires_at"] = time.time() + max(0, seconds - min(60, seconds / 10))
            else:
                payload["expires_at"] = None
            if not refresh and self.scopes:
                scope = payload.get("scope", payload.get("authed_user", {}).get("scope", ""))
                granted = set(scope.replace(",", " ").split())
                if not set(self.scopes) <= granted:
                    raise ValueError("Missing requested scopes")
            # Persist only fields used for account access, not arbitrary provider payloads.
            return {
                key: payload[key]
                for key in (
                    "access_token",
                    "refresh_token",
                    "expires_at",
                    "scope",
                    "team",
                    "authed_user",
                )
                if key in payload
            }
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
            raise ServiceError(
                f"{self.spec.label} authorization failed. Connect the account again."
            ) from error

    async def callback(self, state, code, error=""):
        if not isinstance(state, str) or not 1 <= len(state) <= 256 or len(code) > 4000:
            raise ValueError("Invalid account authorization response.")
        digest = hashlib.sha256(state.encode()).hexdigest()
        row = self.db.one(
            "SELECT owner FROM oauth_states WHERE digest=? AND service=?", (digest, self.spec.name)
        )
        if not row:
            raise ValueError("The authorization link is invalid or expired. Connect again.")
        owner = row["owner"]
        async with self.lock(owner):
            self.authorize(owner)
            # 1. Consume durable state before any exchange, including denied consent.
            with self.db.transaction():
                row = self.db.one(
                    "SELECT * FROM oauth_states WHERE digest=? AND service=? AND expires>?",
                    (digest, self.spec.name, time.time()),
                )
                if not row:
                    raise ValueError("The authorization link is invalid or expired. Connect again.")
                self.db.execute("DELETE FROM oauth_states WHERE digest=?", (digest,))
            saved = self.decode(row["verifier"])
            if error or not code:
                raise ValueError("Account authorization was canceled. Connect again when ready.")
            # 2. Bind the exchange to the original owner, client, endpoint, and verifier.
            fingerprint = self.fingerprint()
            payload = await self.token_request(
                {
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.config.redirect_uri,
                    "code_verifier": saved["verifier"],
                }
            )
            self.authorize(owner)
            if fingerprint != self.fingerprint():
                raise ServiceError("Account configuration changed. Connect again.")
            # 3. Save encrypted tokens only after the exchange and access recheck.
            self.save(owner, payload)
        # Session teardown can authenticate a final DELETE. Release the token lock first.
        await self.close_session(owner)
        return owner

    async def access_token(self, owner):
        self.authorize(owner)
        async with self.lock(owner):
            payload = self.read(owner)
            if payload.get("expires_at") is not None and payload["expires_at"] <= time.time():
                if not payload.get("refresh_token"):
                    raise ServiceError("Account access expired. Connect again.")
                fingerprint = self.fingerprint()
                fresh = await self.token_request(
                    {"grant_type": "refresh_token", "refresh_token": payload["refresh_token"]},
                    refresh=True,
                )
                if fingerprint != self.fingerprint():
                    raise ServiceError("Account configuration changed. Connect again.")
                payload.update(fresh)
                self.save(owner, payload)
            return payload["access_token"]

    async def disconnect(self, owner):
        # Remove the local grant even when the provider is offline or configuration changed.
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("Private account access is required.")
        async with self.lock(owner):
            with self.db.transaction():
                self.db.execute(
                    "DELETE FROM credentials WHERE owner=? AND service=?", (owner, self.spec.name)
                )
                self.db.execute(
                    "DELETE FROM oauth_states WHERE owner=? AND service=?", (owner, self.spec.name)
                )
        await self.close_session(owner)
        return {"disconnected": True, "revoked_at_provider": False}

    async def remote(self, owner, name=None, arguments=None):
        self.authorize(owner)
        # Check saved credentials before creating a task or making a remote request.
        self.read(owner)
        session = self.sessions.get(owner)
        if session is None or session.task.done():
            session = AccountSession(self, owner)
            self.sessions[owner] = session
        return await session.request(name, arguments)

    async def tools(self, owner):
        from .tools import account_tools

        return await account_tools(self, owner)

    async def close_session(self, owner):
        session = self.sessions.pop(owner, None)
        if session is not None:
            await session.close()

    async def close(self):
        self.closed = True
        sessions = list(self.sessions.values())
        self.sessions.clear()
        await asyncio.gather(*(session.close() for session in sessions))
