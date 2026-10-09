"""Explicit memory operations, separate from consented background consolidation."""

from harness import tool


def memory_tools(client, owner):
    """Expose explicit memory operations without automatic conversation ingestion."""

    @tool
    async def save_memory(text: str):
        """Save information that the user explicitly wants to remember."""
        return await client.save(owner, text)

    @tool
    async def search_memory(query: str):
        """Search your saved memories."""
        return await client.search(owner, query)

    @tool
    async def get_all_memories():
        """List your saved memories."""
        return await client.list(owner)

    @tool
    async def get_memory(memory_id: str):
        """Read one of your saved memories."""
        return await client.read(owner, memory_id)

    @tool
    async def update_memory(memory_id: str, text: str):
        """Replace one of your saved memories."""
        return await client.update(owner, memory_id, text)

    @tool
    async def delete_memory(memory_id: str):
        """Delete one of your saved memories."""
        return await client.delete(owner, memory_id)

    return [save_memory, search_memory, get_all_memories, get_memory, update_memory, delete_memory]
