"""Fixed-host Calendar requests with conditional writes and explicit uncertain outcomes."""

from uuid import uuid4

import httpx

from harness.tools import OutcomeUnknown
from theos.services.errors import ServiceError

from .validation import editable_event, event_version, resource_id

EVENT_FIELDS = (
    "id,etag,status,summary,description,location,htmlLink,start,end,eventType,"
    "recurrence,recurringEventId,originalStartTime,attendees,attendeesOmitted,organizer,"
    "transparency,visibility,updated"
)


class Calendar:
    """Bind all requests to the current owner's separate Calendar grant."""

    def __init__(self, oauth, http, settings, db):
        self.oauth, self.http, self.settings, self.db = oauth, http, settings, db

    async def request(self, owner, method, path, *, write=False, headers=None, **kwargs):
        token = await self.oauth.access_token(owner, "calendar")
        response = None
        try:
            response = await self.http.request(
                method,
                "https://www.googleapis.com/calendar/v3/" + path,
                headers={**(headers or {}), "Authorization": "Bearer " + token},
                follow_redirects=False,
                **kwargs,
            )
            if write and (response.status_code >= 500 or response.status_code == 408):
                raise OutcomeUnknown(
                    "The Calendar write outcome is unknown. Check the event before repeating it."
                )
            if response.status_code == 412:
                raise ValueError("The event changed. Read it again before changing or deleting it.")
            response.raise_for_status()
            if not response.is_success:
                raise ServiceError(
                    "Calendar returned an unexpected response. Check the connection."
                )
            if response.status_code == 204:
                return {}
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid Calendar response")
            return result
        except httpx.TransportError as error:
            if write:
                raise OutcomeUnknown(
                    "The Calendar write outcome is unknown. Check the event before repeating it."
                ) from error
            raise ServiceError("Calendar is unavailable. Try the read again later.") from error
        except httpx.HTTPStatusError as error:
            raise ServiceError(
                "Calendar rejected the request. Check account permissions and the resource ID."
            ) from error
        except (ValueError, TypeError) as error:
            if response is not None and response.status_code == 412:
                raise
            if write:
                raise OutcomeUnknown(
                    "Calendar returned an unreadable write response. Check the event before repeating it."
                ) from error
            raise ServiceError("Calendar returned an unreadable response.") from error

    @staticmethod
    def events_path(calendar_id):
        return "calendars/" + resource_id(calendar_id) + "/events"

    async def event(self, owner, calendar_id, event_id):
        return await self.request(
            owner,
            "GET",
            self.events_path(calendar_id) + "/" + resource_id(event_id),
            params={"fields": EVENT_FIELDS},
        )

    async def create(self, owner, calendar_id, body):
        # A known ID lets the owner reconcile a lost create response without another write.
        event_id = uuid4().hex
        try:
            return await self.request(
                owner,
                "POST",
                self.events_path(calendar_id),
                write=True,
                params={"sendUpdates": "none", "fields": EVENT_FIELDS},
                json={**body, "id": event_id},
            )
        except OutcomeUnknown as error:
            raise OutcomeUnknown(
                f"Calendar creation is uncertain. Check calendar {calendar_id!r}, event {event_id!r} "
                "with calendar_get_event before creating another event."
            ) from error

    async def change(self, owner, calendar_id, event_id, etag, changes=None):
        event_version(etag)
        current = await self.event(owner, calendar_id, event_id)
        editable_event(current, etag)
        method = "DELETE" if changes is None else "PATCH"
        kwargs = {"params": {"sendUpdates": "none"}, "headers": {"If-Match": etag}}
        if changes is not None:
            kwargs["params"]["fields"] = EVENT_FIELDS
            kwargs["json"] = changes
        return await self.request(
            owner,
            method,
            self.events_path(calendar_id) + "/" + resource_id(event_id),
            write=True,
            **kwargs,
        )

    def tools(self, owner, *, result_stager=None):
        from .tools import calendar_tools

        return calendar_tools(self, owner, result_stager=result_stager)
