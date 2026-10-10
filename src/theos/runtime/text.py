"""Shared writing rules for assistant output."""

import re

WRITING_RULES = (
    "Never use em dashes in any output, including explanations, reasoning summaries, "
    "quotes, and titles. Use commas, parentheses, or separate sentences instead. "
)
_em_dash = re.compile(r"\u2014|&mdash;|&#0*8212;|&#[xX]0*2014;", re.IGNORECASE)


def reply_text(text: str) -> str:
    """Enforce the punctuation rule even when a provider ignores instructions."""
    return _em_dash.sub("-", text)
