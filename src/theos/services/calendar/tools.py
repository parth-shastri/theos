"""Basic calendar reads and single-event operations for one private owner."""

from typing import Annotated

from pydantic import Field

from harness import tool
from theos.services.preferences.tools import preferences
from theos.services.result_files import for_model

from .client import EVENT_FIELDS
from .validation import event_times, resource_id, timed_range, timezone_name

Title = Annotated[str, Field(min_length=1, max_length=1024)]
Text = Annotated[str, Field(max_length=16000)]
PageToken = Annotated[str, Field(min_length=1, max_length=4096)]


def calendar_tools(client, owner, *, result_stager=None):
    def zone(timezone):
        return timezone_name(
            timezone or preferences(client.db, owner, client.settings.timezone)["timezone"]
        )

    async def result(value, name):
        return await for_model(value, tool_name=name, save_result=result_stager)

    @tool
    async def calendar_connect():
        """Create a Google sign-in link for your separate Calendar account connection."""
        return {"url": client.oauth.start(owner, "calendar")}

    @tool
    async def calendar_disconnect():
        """Disconnect Calendar from Theos. Google app revocation is separate and affects other Google connections sharing its project."""
        return await client.oauth.disconnect(owner, "calendar")

    @tool(parallel_safe=True)
    async def calendar_list_calendars(
        page_token: PageToken | None = None,
        max_results: Annotated[int, Field(ge=1, le=100)] = 25,
    ):
        """List one page of your calendars, IDs, timezones, and access roles.
        max_results limits this response only. Pass next_page_token as page_token
        with the same filters to continue, even when the returned page is short.
        """
        params = {
            "maxResults": max_results,
            "fields": "nextPageToken,items(id,summary,description,timeZone,accessRole,primary)",
        }
        if page_token:
            params["pageToken"] = page_token
        data = await client.request(owner, "GET", "users/me/calendarList", params=params)
        return await result(
            {"calendars": data.get("items", []), "next_page_token": data.get("nextPageToken")},
            "calendar_list_calendars",
        )

    @tool(parallel_safe=True)
    async def calendar_list_events(
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
        query: Annotated[str, Field(max_length=2000)] | None = None,
        timezone: str | None = None,
        page_token: PageToken | None = None,
        max_results: Annotated[int, Field(ge=1, le=100)] = 25,
    ):
        """Find events overlapping an ISO date-time range, optionally filtered by query.
        Naive times use your saved timezone unless timezone is supplied. Recurring
        events appear as instances. max_results limits one response, not total matches.
        Pass next_page_token as page_token with unchanged filters, even after an empty page.
        Use calendar_get_event for details and the current etag before editing or deleting.
        """
        timezone = zone(timezone)
        first, last = timed_range(time_min, time_max, timezone)
        params = {
            "timeMin": first,
            "timeMax": last,
            "timeZone": timezone,
            "singleEvents": "true",
            "orderBy": "startTime",
            "showDeleted": "false",
            "maxResults": max_results,
            "fields": "summary,timeZone,accessRole,nextPageToken,items(" + EVENT_FIELDS + ")",
        }
        if query is not None:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        data = await client.request(owner, "GET", client.events_path(calendar_id), params=params)
        return await result(
            {
                "calendar_id": calendar_id,
                "timezone": data.get("timeZone", timezone),
                "events": data.get("items", []),
                "next_page_token": data.get("nextPageToken"),
            },
            "calendar_list_events",
        )

    @tool(parallel_safe=True)
    async def calendar_get_event(event_id: str, calendar_id: str = "primary"):
        """Read an event's details and etag. Preserve the etag exactly for updates or deletion."""
        return await result(await client.event(owner, calendar_id, event_id), "calendar_get_event")

    @tool(parallel_safe=True)
    async def calendar_free_busy(
        time_min: str,
        time_max: str,
        calendar_ids: Annotated[list[str], Field(min_length=1, max_length=50)] | None = None,
        timezone: str | None = None,
    ):
        """Read busy intervals for up to 50 calendars in an ISO date-time range.
        Defaults to your primary calendar and saved timezone. Report per-calendar
        errors as unavailable information, never as free time. This call only reads availability.
        """
        timezone = zone(timezone)
        first, last = timed_range(time_min, time_max, timezone)
        ids = calendar_ids or ["primary"]
        for identifier in ids:
            resource_id(identifier)
        return await result(
            await client.request(
                owner,
                "POST",
                "freeBusy",
                json={
                    "timeMin": first,
                    "timeMax": last,
                    "timeZone": timezone,
                    "calendarExpansionMax": 50,
                    "groupExpansionMax": 0,
                    "items": [{"id": identifier} for identifier in ids],
                },
            ),
            "calendar_free_busy",
        )

    @tool
    async def calendar_create_event(
        summary: Title,
        start: str,
        end: str,
        calendar_id: str = "primary",
        timezone: str | None = None,
        all_day: bool = False,
        description: Text = "",
        location: Title | None = None,
    ):
        """Create one regular event without attendees or recurrence.
        Timed events use ISO date-times and your saved timezone unless supplied.
        all_day requires YYYY-MM-DD dates with an exclusive end, such as Oct 28 to Oct 29 for one day.
        Resolve the intended time before writing. If creation is uncertain, check the returned event ID before repeating it.
        """
        if not summary.strip():
            raise ValueError("Supply a nonempty event summary.")
        body = {
            "summary": summary,
            "description": description,
            **event_times(start, end, zone(timezone), all_day),
        }
        if location is not None:
            body["location"] = location
        return await result(await client.create(owner, calendar_id, body), "calendar_create_event")

    @tool
    async def calendar_update_event(
        event_id: str,
        etag: str,
        calendar_id: str = "primary",
        summary: Title | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        all_day: bool | None = None,
        description: Text | None = None,
        location: Annotated[str, Field(max_length=1024)] | None = None,
    ):
        """Update or reschedule one regular event using the etag from calendar_get_event.
        Omitted fields stay unchanged. Supply start, end, and all_day together when changing times.
        Set all_day=true for dates with an exclusive end, or false for timed events.
        Events with attendees or recurrence cannot be changed yet. A changed etag requires a fresh read.
        """
        changes = {}
        for name, value in (
            ("summary", summary),
            ("description", description),
            ("location", location),
        ):
            if value is not None:
                if name == "summary" and not value.strip():
                    raise ValueError("Supply a nonempty event summary.")
                changes[name] = value
        if any(value is not None for value in (start, end, all_day, timezone)):
            if start is None or end is None or all_day is None:
                raise ValueError(
                    "Supply start, end, and all_day together when changing event times."
                )
            changes.update(event_times(start, end, zone(timezone), all_day))
            # Clear the previous representation when switching between dates and date-times.
            for boundary in ("start", "end"):
                changes[boundary]["dateTime" if all_day else "date"] = None
                if all_day:
                    changes[boundary]["timeZone"] = None
        if not changes:
            raise ValueError("Supply at least one event change.")
        return await result(
            await client.change(owner, calendar_id, event_id, etag, changes),
            "calendar_update_event",
        )

    @tool
    async def calendar_delete_event(event_id: str, etag: str, calendar_id: str = "primary"):
        """Delete one regular event using the etag from calendar_get_event.
        Verify the intended event first. Events with attendees or recurrence cannot
        be deleted yet. If the outcome is uncertain, check the event before repeating the request.
        """
        await client.change(owner, calendar_id, event_id, etag)
        return {"calendar_id": calendar_id, "event_id": event_id, "deleted": True}

    return [
        calendar_connect,
        calendar_disconnect,
        calendar_list_calendars,
        calendar_list_events,
        calendar_get_event,
        calendar_free_busy,
        calendar_create_event,
        calendar_update_event,
        calendar_delete_event,
    ]
