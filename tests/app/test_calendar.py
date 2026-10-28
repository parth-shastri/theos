"""Calendar account boundaries, pagination, event times, and write uncertainty."""

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from harness.tools import OutcomeUnknown
from theos.services.calendar.client import Calendar
from theos.services.calendar.validation import event_times, resource_id
from theos.services.errors import ServiceError
from theos.services.google.oauth import SCOPES, OAuth
from theos.settings import CalendarSettings, Settings

from .conftest import call_tool
from .test_browser_connections import browser


@pytest.fixture
def configured(runtime):
    runtime.settings.token_encryption_key = SecretStr(Fernet.generate_key().decode())
    runtime.settings.calendar = CalendarSettings(
        client_id="calendar-client",
        client_secret="calendar-secret",
        redirect_uri="http://localhost:8080/oauth/calendar/callback",
    )
    runtime.oauth = OAuth(runtime.settings, runtime.db, runtime.http)
    runtime.calendar = Calendar(runtime.oauth, runtime.http, runtime.settings, runtime.db)
    runtime.db.put_record("alice", "preferences", "settings", {"timezone": "Asia/Kolkata"})
    runtime.oauth.save(
        "alice", "calendar", {"access_token": "alice-token", "expires_at": time.time() + 3600}
    )
    runtime.oauth.save(
        "bob", "calendar", {"access_token": "bob-token", "expires_at": time.time() + 3600}
    )
    return runtime.calendar


def event(**changes):
    return {
        "id": "event123",
        "etag": '"v1"',
        "summary": "Focus block",
        "eventType": "default",
        "status": "confirmed",
        "start": {"dateTime": "2026-10-29T09:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-10-29T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
        **changes,
    }


async def test_calendar_oauth_uses_separate_scopes_state_and_encrypted_owner_grants(
    runtime, configured
):
    requests = []

    def endpoint(request):
        requests.append(request)
        assert request.url.host == "oauth2.googleapis.com"
        data = parse_qs(request.content.decode())
        assert data["code_verifier"] and data["redirect_uri"] == [
            runtime.settings.calendar.redirect_uri
        ]
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-calendar-token",
                "refresh_token": "refresh-secret",
                "expires_in": 3600,
                "scope": " ".join(SCOPES["calendar"]),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        runtime.oauth.http = http
        async with browser(runtime) as alice, browser(runtime, "bob") as bob:
            status = (await alice.get("/api/connections")).json()
            assert next(a for a in status["accounts"] if a["id"] == "calendar")["connected"]
            started = (await alice.post("/api/connections/calendar/connect")).json()
            query = parse_qs(urlsplit(started["url"]).query)
            assert set(query["scope"][0].split()) == set(SCOPES["calendar"])
            assert query["code_challenge_method"] == ["S256"]
            state = query["state"][0]
            denied = await bob.get("/oauth/gmail/callback", params={"state": state, "code": "code"})
            assert denied.status_code != 303
            response = await bob.get(
                "/oauth/calendar/callback", params={"state": state, "code": "code"}
            )
            assert response.status_code == 303 and response.headers["location"] == "/?connections=1"
            assert runtime.oauth.read("alice", "calendar")["access_token"] == "fresh-calendar-token"
            assert runtime.oauth.read("bob", "calendar")["access_token"] == "bob-token"
            encrypted = runtime.db.one(
                "SELECT encrypted FROM credentials WHERE owner='alice' AND service='calendar'"
            )
            assert "fresh-calendar-token" not in encrypted["encrypted"]
            assert (
                await alice.get("/oauth/calendar/callback", params={"state": state, "code": "code"})
            ).status_code == 400
            started = (await alice.post("/api/connections/calendar/connect")).json()
            assert (await alice.post("/api/connections/calendar/cancel")).status_code == 200
            assert runtime.oauth.read("alice", "calendar")["access_token"] == "fresh-calendar-token"
            assert len(requests) == 1


@pytest.mark.parametrize(
    "redirect",
    [
        "https://example.test/wrong",
        "https://user:secret@example.test/oauth/calendar/callback",
        "https://example.test/oauth/calendar/callback?token=secret",
        "http://example.test/oauth/calendar/callback",
    ],
)
def test_calendar_callback_configuration_is_exact(redirect):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            calendar={"client_id": "id", "client_secret": "secret", "redirect_uri": redirect},
            token_encryption_key=Fernet.generate_key().decode(),
        )


async def test_calendar_tools_are_private_and_never_accept_an_owner_argument(runtime, configured):
    for owner, channel, expected in [
        ("alice", "browser", True),
        ("alice", "telegram-group", False),
        ("alice", "terminal", False),
        ("telegram:999", "telegram-private", False),
    ]:
        session = runtime.db.create_session(owner, "test", "none", channel=channel)
        tools = await runtime.tools(session)
        assert any(t.name == "calendar_list_events" for t in tools) == expected
    tool = next(t for t in configured.tools("alice") if t.name == "calendar_get_event")
    with pytest.raises(ValidationError):
        tool.input_model.model_validate({"event_id": "event123", "owner": "bob"})


async def test_event_pagination_preserves_filters_and_empty_page_continuation(runtime, configured):
    calls = []

    def endpoint(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer alice-token"
        params = request.url.params
        assert params["timeZone"] == "Asia/Kolkata"
        assert params["timeMin"] == "2026-10-29T00:00:00+05:30"
        assert params["maxResults"] == "2" and params["q"] == "focus"
        assert params["singleEvents"] == "true"
        assert "hangoutLink" in params["fields"]
        assert "conferenceData(entryPoints(entryPointType,uri,label))" in params["fields"]
        if "pageToken" not in params:
            return httpx.Response(200, json={"items": [], "nextPageToken": "page-two"})
        assert params["pageToken"] == "page-two"
        return httpx.Response(
            200, json={"items": [event(hangoutLink="https://meet.google.com/abc-defg-hij")]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        tools = configured.tools("alice")
        args = dict(
            time_min="2026-10-29T00:00:00",
            time_max="2026-10-30T00:00:00",
            query="focus",
            max_results=2,
        )
        first = await call_tool(tools, "calendar_list_events", **args)
        assert not first["events"] and first["next_page_token"] == "page-two"
        second = await call_tool(
            tools, "calendar_list_events", page_token=first["next_page_token"], **args
        )
        assert second["events"][0]["id"] == "event123" and second["next_page_token"] is None
        assert second["events"][0]["hangoutLink"] == "https://meet.google.com/abc-defg-hij"
        assert len(calls) == 2
        for name in ("calendar_list_events", "calendar_list_calendars"):
            description = " ".join(next(t for t in tools if t.name == name).description.split())
            assert "next_page_token as page_token" in description


async def test_calendar_lists_and_freebusy_preserve_partial_access_errors(runtime, configured):
    def endpoint(request):
        assert request.headers["Authorization"] == "Bearer bob-token"
        if request.url.path.endswith("calendarList"):
            assert request.url.params["pageToken"] == "next"
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "team@example.com", "accessRole": "reader"}],
                    "nextPageToken": "last",
                },
            )
        assert request.method == "POST" and request.url.path.endswith("freeBusy")
        body = json.loads(request.content)
        assert body["timeZone"] == "UTC" and body["groupExpansionMax"] == 0
        return httpx.Response(
            200,
            json={
                "calendars": {
                    "primary": {"busy": []},
                    "missing": {"errors": [{"reason": "notFound"}]},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        tools = configured.tools("bob")
        listed = await call_tool(tools, "calendar_list_calendars", page_token="next")
        assert (
            listed["calendars"][0]["accessRole"] == "reader" and listed["next_page_token"] == "last"
        )
        busy = await call_tool(
            tools,
            "calendar_free_busy",
            time_min="2026-10-29T00:00:00Z",
            time_max="2026-10-30T00:00:00Z",
            timezone="UTC",
        )
        assert busy["calendars"]["missing"]["errors"] == [{"reason": "notFound"}]


@pytest.mark.parametrize(
    "start,end,zone,all_day",
    [
        ("2026-10-29T10:00:00", "2026-10-29T09:00:00", "UTC", False),
        ("2026-10-29", "2026-10-29", "UTC", True),
        ("2026-10-29T00:00:00", "2026-10-30", "UTC", True),
        ("2026-11-01T01:30:00", "2026-11-01T02:30:00", "America/New_York", False),
        ("2026-03-08T02:30:00", "2026-03-08T03:30:00", "America/New_York", False),
    ],
)
def test_event_times_reject_invalid_ranges_and_ambiguous_local_times(start, end, zone, all_day):
    with pytest.raises(ValueError):
        event_times(start, end, zone, all_day)


def test_all_day_end_is_exclusive_and_offsets_resolve_dst():
    assert event_times("2026-10-29", "2026-10-30", "UTC", True) == {
        "start": {"date": "2026-10-29"},
        "end": {"date": "2026-10-30"},
    }
    times = event_times(
        "2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00", "America/New_York"
    )
    assert times["start"]["dateTime"].endswith("-04:00") and times["end"]["dateTime"].endswith(
        "-05:00"
    )


async def test_create_event_uses_known_id_saved_timezone_and_no_invitation_fields(configured):
    sent = []

    def endpoint(request):
        sent.append(request)
        body = json.loads(request.content)
        assert request.method == "POST" and request.url.params["sendUpdates"] == "none"
        assert len(body["id"]) == 32
        assert body["start"] == {
            "dateTime": "2026-10-29T09:00:00+05:30",
            "timeZone": "Asia/Kolkata",
        }
        assert "attendees" not in body and "recurrence" not in body
        return httpx.Response(200, json={**event(), **body})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        result = await call_tool(
            configured.tools("alice"),
            "calendar_create_event",
            summary="Focus",
            start="2026-10-29T09:00:00",
            end="2026-10-29T10:00:00",
        )
        assert result["summary"] == "Focus" and len(sent) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"attendees": [{"email": "guest@example.test"}]},
        {"attendeesOmitted": True},
        {"recurrence": ["RRULE:FREQ=DAILY"]},
        {"recurringEventId": "series123"},
        {"eventType": "fromGmail"},
        {"status": "cancelled"},
        {"etag": '"changed"'},
    ],
)
async def test_deferred_or_changed_events_never_mutate(configured, changes):
    writes = []

    def endpoint(request):
        if request.method != "GET":
            writes.append(request)
        return httpx.Response(200, json=event(**changes))

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        for name, extra in [
            ("calendar_update_event", {"summary": "Changed"}),
            ("calendar_delete_event", {}),
        ]:
            with pytest.raises(ValueError):
                await call_tool(
                    configured.tools("alice"), name, event_id="event123", etag='"v1"', **extra
                )
    assert not writes


async def test_update_is_conditional_preserves_omitted_fields_and_can_change_date_type(configured):
    writes = []

    def endpoint(request):
        if request.method == "GET":
            return httpx.Response(200, json=event(description="Keep this"))
        assert request.method == "PATCH" and request.headers["If-Match"] == '"v1"'
        body = json.loads(request.content)
        writes.append(body)
        assert "description" not in body and "attendees" not in body
        return httpx.Response(200, json=event(**body))

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        await call_tool(
            configured.tools("alice"),
            "calendar_update_event",
            event_id="event123",
            etag='"v1"',
            start="2026-10-29",
            end="2026-10-30",
            all_day=True,
        )
    assert writes == [
        {
            "start": {"date": "2026-10-29", "dateTime": None, "timeZone": None},
            "end": {"date": "2026-10-30", "dateTime": None, "timeZone": None},
        }
    ]


async def test_delete_accepts_empty_success_and_rejects_server_side_etag_race(configured):
    race = False

    def endpoint(request):
        if request.method == "GET":
            return httpx.Response(200, json=event())
        assert request.method == "DELETE" and request.headers["If-Match"] == '"v1"'
        return httpx.Response(412 if race else 204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        assert (
            await call_tool(
                configured.tools("alice"), "calendar_delete_event", event_id="event123", etag='"v1"'
            )
        )["deleted"]
        race = True
        with pytest.raises(ValueError, match="event changed"):
            await call_tool(
                configured.tools("alice"), "calendar_delete_event", event_id="event123", etag='"v1"'
            )


@pytest.mark.parametrize("failure", ["timeout", "server", "invalid_json"])
async def test_uncertain_create_is_not_retried_and_keeps_reconciliation_id(configured, failure):
    sent = []

    def endpoint(request):
        sent.append(json.loads(request.content))
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream detail")
        return (
            httpx.Response(503) if failure == "server" else httpx.Response(200, content=b"not json")
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        with pytest.raises(OutcomeUnknown) as error:
            await call_tool(
                configured.tools("alice"),
                "calendar_create_event",
                summary="Focus",
                start="2026-10-29",
                end="2026-10-30",
                all_day=True,
            )
    assert len(sent) == 1 and sent[0]["id"] in str(error.value)
    assert "private upstream detail" not in str(error.value)


async def test_freebusy_post_failure_remains_a_read_error(configured):
    def endpoint(request):
        raise httpx.ReadTimeout("private upstream detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        configured.http = http
        with pytest.raises(ServiceError, match="read again later"):
            await call_tool(
                configured.tools("alice"),
                "calendar_free_busy",
                time_min="2026-10-29T00:00:00Z",
                time_max="2026-10-30T00:00:00Z",
            )


@pytest.mark.parametrize("identifier", ["", "..", "a/b", "a\\b", "a\nb"])
def test_resource_ids_cannot_escape_fixed_calendar_paths(identifier):
    with pytest.raises(ValueError):
        resource_id(identifier)


async def test_private_telegram_calendar_connect_does_not_use_model_history(runtime, configured):
    from theos.transports.telegram.connections import handle

    runtime.settings.telegram_users.add(123)
    sent = []

    async def send(*args):
        sent.append(args)

    bot = SimpleNamespace(settings=runtime.settings, db=runtime.db, runtime=runtime, send=send)
    assert await handle(
        bot, {"text": "/calendar"}, "telegram:123", "telegram-private", 123, None, None
    )
    url = sent[-1][3]["inline_keyboard"][0][0]["url"]
    assert parse_qs(urlsplit(url).query)["scope"][0].split() == SCOPES["calendar"]
    assert not runtime.db.rows("SELECT * FROM sessions WHERE owner='telegram:123'")


async def test_calendar_disconnect_preserves_other_google_grants(runtime, configured):
    requests = []

    def endpoint(request):
        requests.append(request)
        return httpx.Response(200, json={})

    runtime.oauth.save(
        "alice", "calendar", {"access_token": "calendar-token", "refresh_token": "calendar-refresh"}
    )
    runtime.oauth.save(
        "alice", "gmail", {"access_token": "gmail-token", "refresh_token": "gmail-refresh"}
    )
    gmail = runtime.db.one(
        "SELECT encrypted FROM credentials WHERE owner='alice' AND service='gmail'"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint)) as http:
        runtime.oauth.http = http
        async with browser(runtime) as alice:
            response = (await alice.post("/api/connections/calendar/disconnect")).json()
        assert response["disconnected"] and not response["revoked_at_google"]
        assert "other Google connections" in response["message"]
        assert not runtime.db.one(
            "SELECT 1 FROM credentials WHERE owner='alice' AND service='calendar'"
        )
        assert (
            runtime.db.one(
                "SELECT encrypted FROM credentials WHERE owner='alice' AND service='gmail'"
            )
            == gmail
        )
        assert not requests
