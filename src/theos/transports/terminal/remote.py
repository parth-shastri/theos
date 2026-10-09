"""HTTP client for the deployed workspace, without a local database or runtime."""

import base64
import json
import time
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx

from renderer.events import RunFinished
from renderer.interactive import RuntimeInfo, SessionInfo, normalize_prompt
from theos.storage.messages import restore_message

from .wire import approval_events, decode_event


def server_url(value):
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError("Use an HTTP or HTTPS server URL without credentials, query, or fragment.")
    return value.rstrip("/") + "/"


def timestamp(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value is not None else None


class RemoteSession:
    """Implement the renderer session interface using authenticated server requests."""

    def __init__(self, url, token, *, transport=None):
        if len(token.strip()) < 32:
            raise ValueError("Supply the deployment's browser token with at least 32 characters.")
        self.url = server_url(url)
        self.http = httpx.AsyncClient(
            base_url=self.url,
            headers={"Authorization": "Bearer " + token.strip()},
            timeout=httpx.Timeout(15, read=330),
            follow_redirects=False,
            transport=transport,
        )
        self.info = {}
        self.me = {}
        self._snapshots = {}
        self._seen_notices = set()
        self._notices_checked = 0

    async def connect(self):
        self.me = await self.request("GET", "api/me")
        self.info = await self.request("GET", "api/terminal/info")
        if self.info.get("protocol") != 1:
            raise ValueError("Update the deployment to use this terminal client.")
        self.http.timeout = httpx.Timeout(15, read=self.info["turn_timeout"] + 30)

    async def close(self):
        await self.http.aclose()

    async def check_response(self, response):
        if response.is_success:
            return
        if response.status_code == 401:
            raise ValueError(
                "The deployment rejected your token. Use the same token as browser login."
            )
        if response.status_code == 404:
            raise LookupError(
                "Conversation or endpoint not found. Check the ID and deployment version."
            )
        if response.status_code in {400, 403, 409, 413, 422}:
            await response.aread()
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, str):
                raise ValueError(detail)
            raise ValueError(
                "The deployment rejected this request. Check its values and permissions."
            )
        raise RuntimeError(f"The deployment returned HTTP {response.status_code}.")

    async def request(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise RuntimeError(
                "Could not reach the deployment. Check the server URL and connection."
            ) from None
        await self.check_response(response)
        try:
            return response.json()
        except ValueError:
            raise RuntimeError("The deployment returned an invalid response.") from None

    def path(self, session_id, suffix="", *, terminal=True):
        prefix = "api/terminal/sessions/" if terminal else "api/sessions/"
        return prefix + quote(session_id, safe="") + suffix

    async def snapshot(self, session_id):
        value = await self.request("GET", self.path(session_id, terminal=False))
        self._snapshots[session_id] = value
        return value

    async def sessions(self):
        return tuple(row["id"] for row in await self.request("GET", "api/terminal/sessions"))

    async def session_details(self):
        rows = await self.request("GET", "api/terminal/sessions")
        return tuple(
            SessionInfo(
                row["id"],
                row["title"],
                timestamp(row["created"]),
                timestamp(row["updated"]),
                archived=row["archived"],
            )
            for row in rows
        )

    async def create_session(self, session_id):
        await self.request("POST", "api/terminal/sessions", json={"session_id": session_id})

    async def history(self, session_id):
        return tuple(
            restore_message(value) for value in (await self.snapshot(session_id))["history"]
        )

    async def history_timestamps(self, session_id):
        row = self._snapshots.get(session_id) or await self.snapshot(session_id)
        return tuple(
            timestamp(value.get("display", {}).get("created_at")) for value in row["history"]
        )

    async def session_title(self, session_id):
        return (await self.snapshot(session_id))["title"]

    async def rename_session(self, session_id, title):
        await self.request("PATCH", self.path(session_id), json={"title": title.strip()})

    async def archive_session(self, session_id, archived):
        await self.request("PATCH", self.path(session_id), json={"archived": archived})

    async def pending_interactions(self, session_id):
        return approval_events((await self.snapshot(session_id))["approvals"])

    async def respond(self, replies, *, session_id):
        if any(reply.kind != "approval" or not isinstance(reply.value, bool) for reply in replies):
            raise ValueError("Choose Allow once or Deny for each approval.")
        await self.request(
            "POST",
            self.path(session_id, "/decisions"),
            json={
                "replies": [
                    {"request_id": reply.request_id, "approved": reply.value} for reply in replies
                ]
            },
        )

    async def attachments(self, prompt):
        if len(prompt.text) > 32000 or len(prompt.images) > 10:
            raise ValueError("Use at most 32000 text characters and 10 images per message.")
        ids = []
        for image in prompt.images:
            if not image.url.startswith("data:image/"):
                raise ValueError("Attach a local image or a clipboard image.")
            header, _, encoded = image.url.partition(",")
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise ValueError("The attached image is invalid.") from None
            if len(data) > self.info["max_upload_bytes"]:
                raise ValueError("The image exceeds the deployment's upload limit.")
            value = await self.request(
                "POST",
                "api/files",
                files={
                    "file": (image.filename or "image", data, header[5:].removesuffix(";base64"))
                },
            )
            ids.append(value["id"])
        return ids

    async def steer(self, prompt, *, session_id):
        payload = normalize_prompt(prompt)
        await self.request(
            "POST",
            self.path(session_id, "/steer"),
            json={"text": payload.text, "files": await self.attachments(payload)},
        )

    async def stream(self, prompt, *, session_id):
        pending = await self.pending_interactions(session_id)
        if pending:
            if prompt is not None:
                raise ValueError("Resolve the pending approval before you send another message.")
            for request in pending:
                yield request
            yield RunFinished("waiting_for_approval", pending_count=len(pending))
            return
        suffix = "/resume" if prompt is None else "/turn"
        body = {}
        if prompt is not None:
            payload = normalize_prompt(prompt)
            body = {"text": payload.text, "files": await self.attachments(payload)}
        finished = False
        try:
            async with self.http.stream(
                "POST", self.path(session_id, suffix), json=body
            ) as response:
                await self.check_response(response)
                if response.headers.get("X-Theos-Terminal-Protocol") != "1":
                    raise RuntimeError("The deployment returned an unsupported terminal stream.")
                data = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        try:
                            event = decode_event(json.loads("\n".join(data)))
                        except (ValueError, KeyError, TypeError):
                            raise RuntimeError(
                                "The deployment sent an invalid terminal event."
                            ) from None
                        data = []
                        yield event
                        if isinstance(event, RunFinished) and event.parent_call_id is None:
                            finished = True
                            break
        except httpx.HTTPError:
            raise RuntimeError(
                "The connection closed. The server may still be working. Use /reload to check saved results before retrying."
            ) from None
        if not finished:
            raise RuntimeError(
                "The stream ended before completion. Use /reload to check saved results before retrying."
            )

    async def runtime_info(self, session_id):
        row = await self.snapshot(session_id)
        tools = await self.request("GET", self.path(session_id, "/tools", terminal=False))
        return RuntimeInfo(
            model=row["model"],
            provider=self.info["provider"],
            api=self.info["api"],
            tool_names=tuple(tool["name"] for tool in tools),
            capabilities=("remote workspace",),
            permission_policy="Deployment saved approvals. Allow once or deny. Decisions expire after 15 minutes.",
            storage="Deployment SQLite · " + self.url,
        )

    async def configuration(self, session_id):
        self.me = await self.request("GET", "api/me")
        return {"session": await self.snapshot(session_id), "catalog": self.me}

    async def save_settings(self, session_id, model, reasoning, generation):
        await self.request(
            "PATCH",
            self.path(session_id, terminal=False),
            json={"model": model, "reasoning": reasoning, "generation": generation},
        )

    async def usage(self, session_id):
        return {
            "conversation": (await self.snapshot(session_id))["usage"],
            "total": await self.request("GET", "api/usage"),
        }

    async def notifications(self):
        if time.monotonic() - self._notices_checked < 15:
            return ()
        self._notices_checked = time.monotonic()
        rows = await self.request("GET", "api/notifications")
        fresh = [
            row for row in rows if not row["delivered"] and row["id"] not in self._seen_notices
        ]
        self._seen_notices.update(row["id"] for row in rows)
        return fresh
