"""Google OAuth with one-use state, PKCE, and encrypted per-user credentials."""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from theos.services.errors import ServiceError
from theos.storage.account_access import account_access

SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.modify"],
    "health": [
        "https://www.googleapis.com/auth/googlehealth." + suffix
        for suffix in (
            "activity_and_fitness.readonly",
            "health_metrics_and_measurements.readonly",
            "sleep.readonly",
            "nutrition.readonly",
            "nutrition.writeonly",
        )
    ],
}


class OAuth:
    """Keep application credentials out of tools and general-purpose sandboxes."""

    def __init__(self, settings, db, http):
        self.settings = settings
        self.db = db
        self.http = http
        key = settings.token_encryption_key.get_secret_value()
        self.cipher = Fernet(key.encode()) if key else None
        self.locks = {}

    def config(self, service):
        """Require a known enabled service and an encryption key."""
        if service not in SCOPES:
            raise ValueError("Unknown OAuth service.")
        config = getattr(self.settings, service)
        if not config.enabled or self.cipher is None:
            raise ServiceError("This OAuth integration is disabled.")
        return config

    def start(self, owner, service):
        """Create an authorization URL for an authorized private identity."""
        config = self.config(service)
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("Connect this account from an authorized private workspace.")
        self.db.ensure_user(owner)
        # Only the newest consent link may connect this owner's selected service.
        self.db.execute("DELETE FROM oauth_states WHERE owner=? AND service=?", (owner, service))
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        self.db.execute(
            "INSERT INTO oauth_states VALUES (?,?,?,?,?)",
            (
                hashlib.sha256(state.encode()).hexdigest(),
                owner,
                service,
                self.cipher.encrypt(verifier.encode()).decode(),
                time.time() + 600,
            ),
        )
        self._status(owner, service, "waiting", "Waiting for account sign-in.")
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "scope": " ".join(SCOPES[service]),
                "state": state,
                "response_type": "code",
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    async def token_request(self, service, form):
        """Exchange credentials and reserve time for token refresh."""
        config = self.config(service)
        try:
            response = await self.http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret.get_secret_value(),
                    **form,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload.get("access_token"), str):
                raise ValueError("Missing access token")
            payload["expires_at"] = time.time() + int(payload.get("expires_in", 3600)) - 60
            return payload
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise ServiceError("Google authorization failed. Connect the account again.") from error

    def _status(self, owner, service, status, message):
        self.db.put_record(
            owner, "account_connections", service, {"status": status, "message": message}
        )

    def connection_status(self, owner, service):
        """Describe only this owner's pending or completed account setup."""
        pending = self.db.one(
            "SELECT expires FROM oauth_states WHERE owner=? AND service=?", (owner, service)
        )
        if pending:
            if pending["expires"] <= time.time():
                return {
                    "status": "expired",
                    "message": "Sign-in expired. Connect again to continue.",
                }
            return {"status": "waiting", "message": "Finish sign-in in the opened browser tab."}
        try:
            status = self.db.record(owner, "account_connections", service)
        except LookupError:
            return {"status": "idle"}
        return {key: status[key] for key in ("status", "message")}

    async def cancel(self, owner, service):
        """Cancel pending consent without disconnecting an existing account."""
        if service not in SCOPES or not account_access(self.settings, self.db, owner):
            raise PermissionError("Private account access is required.")
        async with self.locks.setdefault((owner, service), asyncio.Lock()):
            self.db.execute(
                "DELETE FROM oauth_states WHERE owner=? AND service=?", (owner, service)
            )
            self._status(owner, service, "cancelled", "Sign-in cancelled. You can connect later.")

    async def callback(self, service, state, code, error=""):
        """Serialize account changes so disconnection cannot resurrect credentials."""
        self.config(service)
        digest = hashlib.sha256(state.encode()).hexdigest()
        row = self.db.one(
            "SELECT owner FROM oauth_states WHERE digest=? AND service=?", (digest, service)
        )
        if not row:
            raise ValueError("The OAuth state is invalid or expired. Connect the account again.")
        async with self.locks.setdefault((row["owner"], service), asyncio.Lock()):
            try:
                owner = await self.exchange_callback(service, state, code, error=error)
            except Exception as failure:
                self._status(
                    row["owner"],
                    service,
                    "cancelled" if error else "failed",
                    "Sign-in was cancelled. Connect again when ready."
                    if error
                    else str(failure)
                    if isinstance(failure, (ServiceError, ValueError))
                    else "Sign-in could not finish. Connect again to retry.",
                )
                raise
            self._status(owner, service, "connected", "Account connected.")
            return owner

    async def exchange_callback(self, service, state, code, *, error=""):
        """Consume state before the exchange, so concurrent callbacks cannot reuse it."""
        config = self.config(service)
        digest = hashlib.sha256(state.encode()).hexdigest()
        # 1. Consume the one-use state before the network exchange to reject callback replay.
        with self.db.transaction():
            row = self.db.one(
                "SELECT * FROM oauth_states WHERE digest=? AND service=? AND expires>?",
                (digest, service, time.time()),
            )
            if not row:
                raise ValueError(
                    "The OAuth state is invalid or expired. Connect the account again."
                )
            self.db.execute("DELETE FROM oauth_states WHERE digest=?", (digest,))
        owner = row["owner"]
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("This user no longer has account access.")
        if error:
            raise ValueError("Sign-in was cancelled. Connect again when ready.")
        if not code:
            raise ValueError("The sign-in response was incomplete. Connect again.")
        # 2. Exchange the code with the verifier stored for this owner and service.
        verifier = self.cipher.decrypt(row["verifier"].encode()).decode()
        payload = await self.token_request(
            service,
            {
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.redirect_uri,
                "code_verifier": verifier,
            },
        )
        # 3. Check the granted permissions before saving encrypted credentials.
        if not set(SCOPES[service]) <= set(payload.get("scope", "").split()):
            raise ServiceError(
                "Google did not grant all required scopes. Connect the account again."
            )
        if not payload.get("refresh_token"):
            raise ServiceError(
                "Google did not return a refresh token. Revoke the previous grant and connect again."
            )
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("This user no longer has account access.")
        self.save(owner, service, payload)
        return owner

    def save(self, owner, service, payload):
        """Encrypt tokens before storing them for one owner and service."""
        encrypted = self.cipher.encrypt(json.dumps(payload).encode()).decode()
        self.db.execute(
            "INSERT INTO credentials VALUES (?,?,?,?) ON CONFLICT(owner,service) DO UPDATE SET "
            "encrypted=excluded.encrypted,updated=excluded.updated",
            (owner, service, encrypted, time.time()),
        )

    def read(self, owner, service):
        """Decrypt the selected owner credentials without exposing token errors."""
        self.config(service)
        row = self.db.one(
            "SELECT encrypted FROM credentials WHERE owner=? AND service=?", (owner, service)
        )
        if not row:
            raise ServiceError("Connect this account from your private workspace first.")
        try:
            return json.loads(self.cipher.decrypt(row["encrypted"].encode()))
        except (InvalidToken, ValueError) as error:
            raise ServiceError(
                "The saved token cannot be decrypted. Restore the encryption key or connect again."
            ) from error

    async def access_token(self, owner, service):
        """Refresh a token while holding the same lock used by disconnection."""
        if not account_access(self.settings, self.db, owner):
            raise PermissionError("This user no longer has account access.")
        # A refresh must finish before disconnection removes credentials, not recreate them afterward.
        async with self.locks.setdefault((owner, service), asyncio.Lock()):
            payload = self.read(owner, service)
            if payload.get("expires_at", 0) <= time.time():
                fresh = await self.token_request(
                    service,
                    {"grant_type": "refresh_token", "refresh_token": payload["refresh_token"]},
                )
                payload.update(fresh)
                self.save(owner, service, payload)
            return payload["access_token"]

    async def disconnect(self, owner, service):
        """Wait for token exchanges before deleting this account's credentials."""
        if service not in SCOPES:
            raise ValueError("Unknown OAuth service.")
        async with self.locks.setdefault((owner, service), asyncio.Lock()):
            return await self.disconnect_account(owner, service)

    async def disconnect_account(self, owner, service):
        """Stop local access even if Google's revocation endpoint is unavailable."""
        self._status(owner, service, "idle", "Account disconnected.")
        # A user can cancel a pending connection before Google returns any tokens.
        try:
            payload = self.read(owner, service)
        except ServiceError:
            payload = {}
        with self.db.transaction():
            self.db.execute("DELETE FROM credentials WHERE owner=? AND service=?", (owner, service))
            self.db.execute(
                "DELETE FROM oauth_states WHERE owner=? AND service=?", (owner, service)
            )
            if service == "health":
                self.db.execute(
                    "UPDATE jobs SET status='cancelled' WHERE owner=? AND kind IN ('health_import','nutrition') AND status!='completed'",
                    (owner,),
                )
        revoked = False
        if not payload.get("refresh_token"):
            return {"disconnected": True, "revoked_at_google": False}
        try:
            response = await self.http.post(
                "https://oauth2.googleapis.com/revoke", data={"token": payload["refresh_token"]}
            )
            revoked = response.is_success
        except httpx.HTTPError:
            pass
        return {"disconnected": True, "revoked_at_google": revoked}
