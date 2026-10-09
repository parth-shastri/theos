"""Shared HTTP error handling for read-only information services."""

import httpx

from .errors import ServiceError


async def request_json(http, method, url, **kwargs):
    """Report remote failures without exposing credentials or response bodies."""
    try:
        response = await http.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise ServiceError(
            "The service request failed. Check the integration configuration and service status."
        ) from error
