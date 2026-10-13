"""Wire adapters for the pinned compression policy; license in compression_LICENSE."""

from __future__ import annotations

import re
from typing import Any

"""The model-visible compression/elision marker and its matcher.

Tool-call arguments are no longer rewritten by the compressor, but legacy sessions may still
carry this marker inside replayed tool-call arguments. Dependency-free leaf shared by the
elision renderers (``agent.context_compressor``) and the dispatch-boundary detector
(``agent.tool_dispatch_helpers``), so the matcher is derived from the template instead of
re-typing its wording.
"""


# #83714 — this text lands inside the model's OWN replayed tool call, so it must not read like
# something the model would write itself: the bare "...[truncated]" it replaced was imitated into
# new calls and written to disk. Non-prose delimiters, an explicit "not original content"
# disclaimer, and per-instance counts keep a copied marker visibly wrong; the counts also make a
# verbatim copy stale, which is why the marker must never be re-applied.
_COMPRESSION_MARKER_PREFIX = "⟪CONTEXT-COMPRESSION:"
_COMPRESSION_MARKER_TEMPLATE = (
    _COMPRESSION_MARKER_PREFIX
    + " {omitted:,} of {total:,} chars omitted here by the context compressor. "
    "This is NOT part of the original tool call and must never be reproduced in new "
    "output — always write full, untruncated content.⟫"
)

# A rendered omitted/total count inside a minted marker.
_MARKER_COUNT_RE = r"\d[\d,]*"

# Full rendered first sentence of a minted marker; renderer tests assert this shape
# (the dispatch guard uses _COMPRESSION_MARKER_ARTIFACT_RE below).
_COMPRESSION_MARKER_RE = re.compile(
    re.escape(_COMPRESSION_MARKER_TEMPLATE.split(". ", 1)[0] + ".")
    .replace(re.escape("{omitted:,}"), _MARKER_COUNT_RE)
    .replace(re.escape("{total:,}"), _MARKER_COUNT_RE)
)

# A marker cut by a later boundary may never reach the fixed sentence above. The
# dispatch guard therefore recognizes a minted marker as soon as its first numeric
# count is present. Requiring that rendered count keeps the bare prefix/template
# editable in source and documentation.
_COMPRESSION_MARKER_ARTIFACT_RE = re.compile(
    re.escape(_COMPRESSION_MARKER_PREFIX) + r"\s+" + _MARKER_COUNT_RE
)

# #121548 — every OTHER model-visible elision (turn text, summaries, skill bodies, diagnostics)
# mints the args marker's first sentence only (so the dispatch-boundary artifact
# matcher catches a copy from any renderer) and fits small caps like clarify's 199.
_ELISION_MARKER_TEMPLATE = _COMPRESSION_MARKER_TEMPLATE.split(". ", 1)[0] + ".⟫"


def _elision_marker(omitted: int, total: int) -> str:
    """Render the non-imitable elision marker with per-instance byte counts."""
    return _ELISION_MARKER_TEMPLATE.format(omitted=omitted, total=total)


# Widest marker for any text under ~1 TB: callers with a small leftover budget skip the item
# when the budget cannot hold the marker plus content, instead of emitting a marker-only line.
ELISION_MARKER_MAX_LEN = len(_elision_marker(omitted=10**12 - 1, total=10**12 - 1))


def elide(text: str, limit: int) -> str:
    """Cap ``text`` at ``limit`` chars, marking the elision with ``_elision_marker``.

    Every model-visible renderer must truncate through here (#121548). ``text`` is
    returned unchanged when it already fits. Otherwise the result is ``head + marker``
    with accurate omitted/total counts and never exceeds ``limit`` (sized against the
    widest rendering the counts can take), unless ``limit`` cannot hold the marker at
    all, in which case the marker alone is returned.
    """
    if len(text) <= limit:
        return text
    total = len(text)
    head_len = limit - len(_elision_marker(omitted=total, total=total))
    if head_len <= 0:
        return _elision_marker(omitted=total, total=total)
    kept = text[:head_len].rstrip()
    return kept + _elision_marker(omitted=total - len(kept), total=total)


def elide_middle(text: str, head: int, tail: int) -> str:
    """Keep ``head`` chars from the start and ``tail`` from the end, eliding the middle."""
    if len(text) <= head + tail:
        return text
    marker = _elision_marker(omitted=len(text) - head - tail, total=len(text))
    return text[:head] + marker + text[len(text) - tail :]


CHARS_PER_TOKEN = 4

_CJK_DENSE_RE = re.compile(
    "[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
)


def estimate_tokens_rough(text: str) -> int:
    """Rough token estimate: CJK/Hangul/Kana codepoints ~1 token each; everything else ceil(UTF-8 bytes/4).
    Ceiling keeps short texts from estimating 0. Runs on every preflight walk, so all-ASCII stays O(1).

    Byte-counting (not chars) is the corrective for non-CJK, non-ASCII text: Cyrillic/Greek/Arabic are 2
    bytes/char so count ~chars/2, matching real BPE cost (~2-3 chars/token) where chars/4 under-counted
    ~2x and let sessions ride the provider ceiling below the compaction threshold. Calibrated vs
    cl100k/o200k/Qwen2.5 (estimate/real): Russian 0.67->1.24, Arabic 0.53->0.96, Hindi 0.34->0.90,
    Greek 0.37->0.68; accented Latin barely moves (French 1.02->1.03). errors="replace": lone surrogates
    (routine in tool output; see message_sanitization) must not turn an estimate into a raise."""
    if not text:
        return 0
    text = str(text)
    if text.isascii():  # flag check on CPython; ASCII cannot contain token-dense CJK
        return (len(text) + 3) // CHARS_PER_TOKEN
    stripped = _CJK_DENSE_RE.sub("", text)
    dense = len(text) - len(stripped)
    return dense + ((len(stripped.encode("utf-8", "replace")) + 3) // CHARS_PER_TOKEN)


def strip_opaque_replay_items(items: Any) -> Any:
    """``codex_reasoning_items`` with ``encrypted_content`` blanked for local token estimation.
    The ciphertext is priced by the provider's own count, never by its bytes (a compaction
    checkpoint alone can be 5M chars, #100611); only real usage prices it."""
    if not isinstance(items, list):
        return items
    return [
        {k: ("" if k == "encrypted_content" else v) for k, v in item.items()}
        if isinstance(item, dict)
        else item
        for item in items
    ]


def estimate_messages_tokens_rough(messages, *, charge_stale_thinking=True):
    from .compression_policy import _estimate_msg_budget_tokens

    return sum(_estimate_msg_budget_tokens(m, charge_stale_thinking) for m in messages)


def redact_sensitive_text(text, *, force=True, redact_url_credentials=True):
    # Provider credentials stay in the runtime; also redact credential-shaped source text.
    text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", str(text))
    return re.sub(
        r"(?i)((?:api[_-]?key|password|secret|access_token)\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        text,
    )


def strip_think_blocks(_, text):
    return re.sub(r"<(?:think|thinking)>.*?</(?:think|thinking)>", "", text, flags=re.S | re.I)


def sanitize_memory_context(value):
    return value.strip() if isinstance(value, str) else ""


def drop_stale_api_content(message):
    message.pop("api_content", None)


def outbound_image_retire_count():
    return 2


def current_image_token_cost():
    return 4096


def parse_context_limit_from_error(error_msg: str) -> int | None:
    """Context limit quoted in a provider error ("maximum context length is 32768 tokens"), if any.

    A message about only an OUTPUT cap ("... model output limit of 16384") never says "context";
    bail out so the generic "limit ... of N" pattern can't cache the output cap as the window."""
    error_lower = error_msg.lower()
    if (
        "output limit" in error_lower
        or "output tokens" in error_lower
        or "output token" in error_lower
    ) and "context" not in error_lower:
        return None
    patterns = (
        r"max_model_len\s*(?:is\s*)?[:=(]?\s*(\d{4,})",  # vLLM: "max_model_len 32768", "=32768", ": 32768", "(32768)", "is 32768"
        r"maximum model length\s*(?:is\s*)?[:=(]?\s*(\d{4,})",  # vLLM alt: "maximum model length 131072", "... is 131072"
        r"(?:max(?:imum)?|limit)\s*(?:context\s*)?(?:length|size|window)?\s*(?:is|of|:)?\s*(\d{4,})",
        r"context\s*(?:length|size|window)\s*(?:is|of|:)?\s*(\d{4,})",
        r"(\d{4,})\s*(?:token)?\s*(?:context|limit)",
        r">\s*(\d{4,})\s*(?:max|limit|token)",  # "250000 tokens > 200000 maximum"
        r"(\d{4,})\s*(?:max(?:imum)?)\b",  # "200000 maximum"
        # Gemini: "input token count is 32825 but model only supports up to
        # 32768" — anchor on the phrase so the input count isn't captured.
        r"supports?\s+(?:only\s+)?up\s+to\s+(\d{4,})",
    )
    for match in filter(None, (re.search(pattern, error_lower) for pattern in patterns)):
        limit = int(match.group(1))
        if 1024 <= limit <= 10_000_000:  # sanity: must be a plausible window
            return limit
    return None
