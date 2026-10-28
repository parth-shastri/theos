"""Search tools with bounded responses."""

from urllib.parse import urlsplit

from harness import tool
from theos.services.errors import ServiceError
from theos.services.http import request_json


def _media_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        url = urlsplit(value)
        return (
            value
            if url.scheme in {"http", "https"}
            and url.hostname
            and not url.username
            and not url.password
            else None
        )
    except ValueError:
        return None


def search_media(data):
    """Retain provider payloads and expose consistent source image fields."""
    rows = data.get("results") or data.get("web", {}).get("results", [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        thumbnail = row.get("thumbnail") or {}
        profile = row.get("profile") or {}
        meta = row.get("meta_url") or {}
        thumbnail = thumbnail if isinstance(thumbnail, dict) else {}
        profile = profile if isinstance(profile, dict) else {}
        meta = meta if isinstance(meta, dict) else {}
        image = (
            _media_url(row.get("image"))
            or _media_url(thumbnail.get("src"))
            or _media_url(thumbnail.get("original"))
        )
        logo = (
            _media_url(row.get("favicon"))
            or _media_url(profile.get("img"))
            or _media_url(meta.get("favicon"))
        )
        if image:
            row["image_url"] = image
            alt = thumbnail.get("alt")
            if isinstance(alt, str) and alt.strip():
                row["image_alt"] = alt.strip()[:300]
        if logo:
            row["logo_url"] = logo
    return data


def search_tools(settings, http):
    """Build Exa search with an optional Brave fallback."""

    @tool
    async def web_search(query: str, count: int = 5):
        """Search with Exa. Use Brave if Exa fails or is not configured."""
        count = min(10, max(1, count))
        if settings.exa_key.get_secret_value():
            try:
                return search_media(
                    await request_json(
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
                )
            except ServiceError:
                # Use the fallback only when its own credentials exist.
                if not settings.brave_key.get_secret_value():
                    raise
        if settings.brave_key.get_secret_value():
            return search_media(
                await request_json(
                    http,
                    "GET",
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": settings.brave_key.get_secret_value()},
                    params={"q": query, "count": count},
                )
            )
        raise ServiceError("Configure an Exa or Brave API key to use search.")

    return [web_search]
