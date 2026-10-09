"""Short, deterministic conversation titles without an extra model call."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any


def conversation_title(history: Sequence[Any], *, limit: int = 64) -> str:
    """Use the first substantive user request; skip greetings and prompt wrappers."""
    saw_greeting = False
    saw_image = False
    for message in history:
        if not type(message).__name__.lower().startswith('user'):
            continue
        saw_image |= bool(getattr(message, 'images', ()))
        content = str(getattr(message, 'content', '')).strip()
        if re.fullmatch(r'(hi|hello|hey|hey there|good (morning|afternoon|evening))[!.\s]*',
                        content, re.IGNORECASE):
            saw_greeting = True
            continue
        # Prefer the task section over IDE/environment context in pasted prompts.
        content = re.split(r'(?im)^\s*#{1,6}\s*(?:my request|task|request)\s*:\s*$', content)[-1]
        content = re.sub(r'(?s)```.*?```|<[^>]+>', ' ', content)
        lines = [re.sub(r'^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)', '', line).strip()
                 for line in content.splitlines() if line.strip()]
        if not lines:
            continue
        text = ' '.join(lines)
        text = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'[*_`]', '', text)
        text = re.sub(r'^(?:(?:hi|hello|hey)[,!]\s*)?(?:please\s+)?'
                      r'(?:(?:can|could|would) you\s+|i (?:want|need|would like) to\s+|'
                      r'help me\s+)?(?:please\s+)?', '', text, flags=re.IGNORECASE)
        text = ' '.join(text.split()).strip(' .!?')
        if not text:
            continue
        # A complete first sentence is more useful than a clipped prompt dump.
        text = re.split(r'[.!?]\s+', text, maxsplit=1)[0]
        text = text[0].upper() + text[1:]
        if len(text) > limit:
            clipped = text[:limit - 1].rsplit(' ', 1)[0]
            text = (clipped or text[:limit - 1]).rstrip(' ,;:') + '…'
        return text
    return 'Photo conversation' if saw_image else 'Greeting' if saw_greeting else 'New conversation'
