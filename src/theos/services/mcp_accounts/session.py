"""Keep remote MCP contexts in one task without repeating failed calls."""

import asyncio

import httpx
from httpx import AsyncClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from theos.services.errors import ServiceError


class AccountAuth(httpx.Auth):
    def __init__(self, account, owner):
        self.account, self.owner = account, owner

    async def async_auth_flow(self, request):
        # Recheck local access for every HTTP request, including an existing session.
        token = await self.account.access_token(self.owner)
        request.headers["Authorization"] = "Bearer " + token
        yield request


class AccountSession:
    """Serialize calls for one credential and close contexts in their creating task."""

    def __init__(self, account, owner):
        self.account, self.owner = account, owner
        self.queue = asyncio.Queue()
        self.active = None
        self.task = asyncio.create_task(self.run())

    async def request(self, name=None, arguments=None):
        if self.task.done():
            raise ServiceError("The account session ended. Check the connection.")
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((future, name, arguments))
        try:
            return await future
        except asyncio.CancelledError:
            await self.close()
            raise

    async def run(self):
        try:
            async with AsyncClient(
                auth=AccountAuth(self.account, self.owner),
                headers=self.account.spec.headers,
                timeout=30,
                follow_redirects=False,
            ) as http:
                async with streamable_http_client(self.account.spec.endpoint, http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        async with asyncio.timeout(30):
                            await session.initialize()
                        while True:
                            self.active, name, arguments = await self.queue.get()
                            async with asyncio.timeout(60):
                                if name is None:
                                    result, cursor, seen = [], None, set()
                                    while True:
                                        page = await session.list_tools(cursor=cursor)
                                        result.extend(page.tools)
                                        cursor = page.nextCursor
                                        if not cursor:
                                            break
                                        if cursor in seen or len(result) > 2000:
                                            raise ValueError("Invalid tool discovery pagination")
                                        seen.add(cursor)
                                else:
                                    result = await session.call_tool(name, arguments)
                            if not self.active.done():
                                self.active.set_result(result)
                            self.active = None
        except Exception:
            # Provider errors can contain tokens or private data. Do not forward them.
            pass
        finally:
            pending = [self.active] if self.active is not None else []
            while not self.queue.empty():
                pending.append(self.queue.get_nowait()[0])
            for future in pending:
                if not future.done():
                    future.set_exception(
                        ServiceError("The remote account is unavailable. Check the connection.")
                    )

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
