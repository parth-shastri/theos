"""Retain each account's Zepto store context across approved tool calls."""

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from theos.services.errors import ServiceError


class ZeptoSession:
    """Keep MCP contexts in one task and serialize calls for one account."""

    def __init__(self, endpoint, provider):
        self.endpoint = endpoint
        self.provider = provider
        self.queue = asyncio.Queue()
        self.active = None
        self.task = asyncio.create_task(self._run())

    async def request(self, name=None, arguments=None):
        if self.task.done():
            raise ServiceError("The Zepto session ended. Establish the delivery store again.")
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((future, name, arguments))
        try:
            return await future
        except asyncio.CancelledError:
            # A canceled action can have uncertain effects. Never replay it.
            await self.close()
            raise

    async def _run(self):
        try:
            async with httpx.AsyncClient(timeout=30, auth=self.provider) as http:
                async with streamable_http_client(self.endpoint, http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(read, write) as session:
                        async with asyncio.timeout(30):
                            await session.initialize()
                        while True:
                            self.active, name, arguments = await self.queue.get()
                            async with asyncio.timeout(30):
                                response = (
                                    await session.list_tools()
                                    if name is None
                                    else await session.call_tool(name, arguments)
                                )
                            if not self.active.done():
                                self.active.set_result(response)
                            self.active = None
        except Exception:
            # Unknown transport errors can include credentials or response bodies.
            # Fail the current action and queue. A later request can open a new session.
            pass
        finally:
            self._reject_pending()

    def _reject_pending(self):
        pending = [self.active] if self.active is not None else []
        while not self.queue.empty():
            pending.append(self.queue.get_nowait()[0])
        for future in pending:
            if not future.done():
                future.set_exception(
                    ServiceError(
                        "The Zepto session ended. Check the action result before retrying. "
                        "Establish the delivery store again for future searches."
                    )
                )
        self.active = None

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self._reject_pending()
