"""Output space accounting shared by answer and summary requests."""

from harness.types import ModelRequest

DEFAULT_OUTPUT_RESERVATION = 8192


def requested_output_tokens(
    request: ModelRequest, fallback: int = DEFAULT_OUTPUT_RESERVATION
) -> int:
    """Reserve the requested output allowance without changing generation options."""
    for key in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
        value = request.options.get(key)
        if type(value) is int and value > 0:
            return value
    # Unknown output limits use the shared space estimate, never a generation cap.
    return fallback
