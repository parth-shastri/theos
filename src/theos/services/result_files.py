"""Keep oversized provider reads out of the model's inline context."""

import json

# Keep ordinary tool replies inline and move only clearly large reads to a file.
INLINE_LIMIT_BYTES = 8 * 1024
# Bound transient disk use; anything larger gets the same safe preview fallback.
MAX_RESULT_BYTES = 1024 * 1024
# A failed write must still produce a useful result without filling model context.
PREVIEW_BYTES = 4 * 1024


async def for_model(value, *, tool_name, summary="", save_result=None):
    """Return small results inline and stage larger, already-shaped results temporarily."""
    content = json.dumps(value, ensure_ascii=False, indent=2)
    data = content.encode("utf-8")
    if len(data) <= INLINE_LIMIT_BYTES:
        return value

    # A staged result is scratch data, not a durable copy of the provider response.
    if save_result and len(data) <= MAX_RESULT_BYTES:
        try:
            saved = await save_result(tool_name, content)
        except Exception:
            # A failed scratch write must never turn a useful read into a context overflow.
            saved = None
        if saved:
            return {
                "summary": summary[:240] or f"Large result from {tool_name}.",
                "result_file": saved["path"],
                "result_bytes": len(data),
                "truncated": False,
                "message": (
                    "The full normalized result is temporarily staged. Use run_command to inspect a "
                    "small file or selected sections with grep or sed. "
                    "If the file is missing, repeat the provider read with narrower arguments."
                ),
            }

    # Keep the fallback small; the provider tool can be called again with narrower filters.
    preview = data[:PREVIEW_BYTES].decode("utf-8", errors="ignore")
    return {
        "summary": summary[:240] or f"Read result from {tool_name}.",
        "preview": preview,
        "result_bytes": len(data),
        "truncated": True,
        "message": (
            "The full result could not be staged. This preview is incomplete; repeat the "
            "provider read with narrower arguments such as a smaller range, fewer results, "
            "or selected metrics."
        ),
    }
