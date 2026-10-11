"""Output space accounting shared by answer and summary requests."""

from harness.types import ModelRequest


def requested_output_tokens(request: ModelRequest, fallback: int = 1024) -> int:
    """Reserve the requested output allowance without changing generation options."""
    for key in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
        value = request.options.get(key)
        if type(value) is int and value > 0:
            return value
    # Generic callers without an output setting retain their explicit space estimate.
    return fallback
