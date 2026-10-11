"""Explicit research entry points. Model output cannot enable research mode."""

import re

PREFIX = re.compile(
    r"^\s*(?:/research\s+|deep research\s*:\s*|(?:please\s+)?"
    r"(?:do|run|start|conduct|perform)\s+(?:a\s+)?deep research"
    r"(?:\s+(?:on|into|about|for)\s+|\s*:\s*))(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def explicit_request(text, mode="normal"):
    """Accept an explicit mode or an anchored user command, never a topic mention."""
    if mode not in {"normal", "deep_research"}:
        raise ValueError("Choose normal or deep_research mode.")
    match = PREFIX.match(text or "")
    if mode == "deep_research" or match:
        task = match.group(1).strip() if match else (text or "").strip()
        if not task:
            raise ValueError("Enter a deep research question.")
        return task
    return None
