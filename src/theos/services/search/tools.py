"""Search tools with bounded responses."""

from harness import tool
from theos.services.errors import ServiceError
from theos.services.http import request_json


def search_tools(settings, http):
    """Build Exa search with an optional Brave fallback."""

    @tool
    async def web_search(query: str, count: int = 5):
        """Search with Exa. Use Brave if Exa fails or is not configured."""
        count = min(10, max(1, count))
        if settings.exa_key.get_secret_value():
            try:
                return await request_json(
                    http,
                    "POST",
                    "https://api.exa.ai/search",
                    headers={"x-api-key": settings.exa_key.get_secret_value()},
                    json={
                        "query": query,
                        "numResults": count,
                        "contents": {"text": {"maxCharacters": 4000}},
                    },
                )
            except ServiceError:
                # Use the fallback only when its own credentials exist.
                if not settings.brave_key.get_secret_value():
                    raise
        if settings.brave_key.get_secret_value():
            return await request_json(
                http,
                "GET",
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": settings.brave_key.get_secret_value()},
                params={"q": query, "count": count},
            )
        raise ServiceError("Configure an Exa or Brave API key to use search.")

    return [web_search]
