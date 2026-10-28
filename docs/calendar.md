# Connect Google Calendar

The Calendar service uses Google Calendar API v3 through HTTPX and the existing Google OAuth service.
Each private owner authorizes a separate Calendar connection. Gmail tokens do not provide Calendar access.

## Configure the deployment

1. Enable the Google Calendar API in the OAuth client's Google Cloud project.
2. Register the exact Calendar callback on the web application's OAuth client.
3. Set the Calendar client ID, client secret, and callback in the private environment.
4. Retain the existing valid token encryption key.
5. Restart the API and open Connections > Google Calendar.
6. Select Connect and authorize the requested permissions.

For the current local Docker test, use this callback:

```text
http://localhost:8080/oauth/calendar/callback
```

For a hosted deployment, register its HTTPS origin followed by `/oauth/calendar/callback`.
The operator selected the existing Gmail OAuth client for local testing.
Its client settings were copied into the ignored private environment.
The operator registered localhost and deployment callbacks. Local sign-in and read operations passed.

```dotenv
AGENT_CALENDAR__CLIENT_ID=your-google-oauth-client-id
AGENT_CALENDAR__CLIENT_SECRET=your-google-oauth-client-secret
AGENT_CALENDAR__REDIRECT_URI=http://localhost:8080/oauth/calendar/callback
AGENT_TOKEN_ENCRYPTION_KEY=your-existing-fernet-key
```

The authorization requests these scopes:

- `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
- `https://www.googleapis.com/auth/calendar.events`
- `https://www.googleapis.com/auth/calendar.events.freebusy`

The first scope lists calendars. The second reads and changes events where the user has permission.
The third reads availability. The service does not request calendar sharing or access-control management.
Enable all requested permissions during consent. Missing permissions leave the previous connection unchanged.

See Google's [Calendar authorization guide](https://developers.google.com/workspace/calendar/api/auth).

## Basic operations

The service lists calendars, finds events, reads event details, and checks free/busy intervals.
It creates, updates, reschedules, and deletes regular single events without attendees.
Invitations and recurring-event mutations are outside this increment.
Events with attendees, recurrence, or specialized event types remain readable but cannot be changed through these tools.

Timed events use ISO date-times. A missing offset uses the owner's saved timezone unless the tool supplies another IANA timezone.
Ambiguous or missing daylight-saving times require an explicit offset.
All-day events use dates and an exclusive end date. An event on October 28 alone ends on October 29.

List tools return one page and a `next_page_token` when another page exists.
Continue with the same filters, including after a short or empty page.
Page sizes and staged-result metadata describe one response. They do not establish complete provider coverage.
Free/busy responses retain individual calendar errors. An unavailable calendar does not establish free time.

Before an update or deletion, read the intended event and supply its exact `etag`.
The service checks that version and sends `If-Match` to prevent concurrent changes from being overwritten.
Updates preserve omitted fields. Time changes require start, end, and the all-day flag together.

A failed write can have an unknown outcome. The service does not retry it automatically.
Event creation uses a known event ID. Read that ID before repeating an uncertain creation.

## Connections and disconnection

Browser and private Telegram owners use their own grants. Connected terminal clients share their authenticated browser owner's tools.
Groups, research delegates, and standalone terminal identities receive no Calendar account tools.
Private Telegram supports `/calendar`, `/connect_calendar`, and `/disconnect_calendar`.

Calendar Disconnect removes the local grant and pending authorization without revoking the whole Google project.
Google's revocation endpoint invalidates other grants in the same project, including other Google service connections.
Use Google Account settings when you intend to revoke the application's Google access.
See Google's [token revocation contract](https://developers.google.com/identity/protocols/oauth2/web-server#tokenrevoke).

## Implementation and acceptance

Provider code lives under `src/theos/services/calendar/`. The generic harness remains unchanged.
The service uses existing HTTPX, Pydantic, Google OAuth, and timezone dependencies. No provider SDK or database migration is required.
Contract tests use mocked Calendar responses. Local authorization, calendar listing, event search, and availability passed against Google.
An operator-approved temporary event also passed live creation, rescheduling, and deletion.
A separate Google API read confirmed that the deleted event has status `cancelled`.
See [runtime acceptance](runtime/acceptance.md) for recorded results.
