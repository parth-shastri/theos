"""Compose read-only tools for normal turns and delegated research."""

from .search.tools import search_tools
from .skills.tools import skills_tools
from .weather.tools import weather_tools


def information_tools(settings, http):
    """Build the configured search, weather, and skill tools."""
    return [
        *search_tools(settings, http),
        *weather_tools(settings, http),
        *skills_tools(settings, http),
    ]
