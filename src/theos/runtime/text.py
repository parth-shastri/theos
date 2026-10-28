"""Shared personality and writing rules for assistant output."""

import re

from theos.prompts import render

PERSONALITY = render("shared/personality.md")

WRITING_RULES = render("shared/writing.md")
_em_dash = re.compile(r"\u2014|&mdash;|&#0*8212;|&#[xX]0*2014;", re.IGNORECASE)


def reply_text(text: str) -> str:
    """Enforce the punctuation rule even when a provider ignores instructions."""
    return _em_dash.sub("-", text)
