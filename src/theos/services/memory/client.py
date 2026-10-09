"""Mem0 HTTP requests and user ownership checks."""

from urllib.parse import quote

import httpx

from theos.services.errors import ServiceError


class MemoryClient:
    """Keep the Mem0 wire format and ownership checks in one client."""

    def __init__(self, settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def request(self, method, path, **kwargs):
        """Call the configured memory API and sanitize integration failures."""
        if not self.settings.enabled:
            raise ServiceError("Memory is disabled. Configure the external memory endpoint.")
        headers = {}
        if self.settings.api_key.get_secret_value():
            headers[self.settings.auth_header] = (
                self.settings.auth_prefix + self.settings.api_key.get_secret_value()
            )
        try:
            response = await self.http.request(
                method,
                self.settings.endpoint.rstrip("/") + path,
                headers=headers,
                timeout=self.settings.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json() if response.content else {"success": True}
        except (httpx.HTTPError, ValueError) as error:
            raise ServiceError(
                "The memory service request failed. Check its status and endpoint."
            ) from error

    async def save(self, owner, text):
        """Save explicitly supplied text under the authenticated owner."""
        return await self.request(
            "POST",
            "/memories",
            json={"messages": [{"role": "user", "content": text}], "user_id": owner},
        )

    async def search(self, owner, query):
        """Search memories and hide results without matching ownership."""
        result = await self.request(
            "POST", "/search", json={"query": query, "filters": {"user_id": owner}}
        )
        return self.owned_results(owner, result)

    async def consolidate(self, owner, rows):
        """Submit consented user messages for Mem0's inference and duplicate handling."""
        return await self.request(
            "POST",
            "/memories",
            json={
                "messages": [{"role": "user", "content": row["content"]} for row in rows],
                "user_id": owner,
                "metadata": {
                    "source": "theos_consolidation",
                    "source_ids": [r["id"] for r in rows],
                },
            },
        )

    async def list(self, owner):
        """List only memories with matching ownership metadata."""
        result = await self.request("GET", "/memories", params={"user_id": owner})
        return self.owned_results(owner, result)

    @staticmethod
    def owned_results(owner, result):
        """Reject malformed responses and filter results by owner."""
        rows = result.get("results", []) if isinstance(result, dict) else result
        if not isinstance(rows, list):
            raise ServiceError("The memory service returned an invalid result list.")
        # Fail closed when the service omits ownership. Never trust an ID alone.
        return [row for row in rows if isinstance(row, dict) and row.get("user_id") == owner]

    async def read(self, owner, memory_id):
        """Read a memory only after checking its remote owner."""
        result = await self.request("GET", f"/memories/{quote(memory_id, safe='')}")
        if not isinstance(result, dict) or result.get("user_id") != owner:
            raise LookupError("Memory not found.")
        return result

    async def update(self, owner, memory_id, text):
        """Replace memory text after checking remote ownership."""
        # Check the remote owner before a write because a memory ID alone grants no access.
        await self.read(owner, memory_id)
        return await self.request(
            "PUT", f"/memories/{quote(memory_id, safe='')}", json={"text": text}
        )

    async def delete(self, owner, memory_id):
        """Delete a memory after checking remote ownership."""
        # Check the remote owner before a write because a memory ID alone grants no access.
        await self.read(owner, memory_id)
        return await self.request("DELETE", f"/memories/{quote(memory_id, safe='')}")
