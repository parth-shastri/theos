"""Private catalog and R2 file operations."""

from harness import tool


def file_tools(files, owner):
    """Build catalog and R2 tools bound to the authenticated owner."""

    @tool
    async def list_user_files():
        """List your uploaded and generated files."""
        return files.list(owner)

    @tool
    async def archive_user_file(file_id: str):
        """Archive a file in the configured R2 bucket."""
        return await files.archive(owner, file_id)

    @tool
    async def restore_user_file(file_id: str):
        """Restore one of your archived files."""
        return await files.restore(owner, file_id)

    @tool
    async def delete_user_file(file_id: str):
        """Delete your file from local storage and R2."""
        return await files.delete(owner, file_id)

    return [list_user_files, archive_user_file, restore_user_file, delete_user_file]
