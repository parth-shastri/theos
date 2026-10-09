# Google Health

The connector imports recent Health summaries and exports local meals as nutrition records.
It requires an authenticated browser or allowed private Telegram user and a separate account authorization.
The application does not access Apple Health directly.
Imported metrics depend on the connected Google account and its upstream data sources.

## Configure the service

These steps belong to the deployment operator.
A self-hosted owner uses their own Google project.
A hosted service operator configures one project for the service.
Each user then authorizes their own Health account.
See [deployment options](DEPLOYMENT.md#choose-a-deployment-option).

Google currently does not onboard new Health API projects.
Check [Health availability](https://developers.google.com/health/get-started) before configuring a new installation.

1. Enable Google Health API access for your project and account.
2. Add all five scopes listed below under **Google Auth Platform > Data Access > Add or remove scopes**.
3. Save the scopes without removing permissions that your other applications require.
4. Create or select a **Web application** client under **Google Auth Platform > Clients**.
5. Register the exact Health callback URI under **Authorized redirect URIs**.
6. Set all three Health client fields in `.env`.
7. Set a valid `AGENT_TOKEN_ENCRYPTION_KEY`.
8. Recreate the application container.

```dotenv
AGENT_HEALTH__CLIENT_ID=replace-me
AGENT_HEALTH__CLIENT_SECRET=replace-me
AGENT_HEALTH__REDIRECT_URI=https://assistant.example.com/oauth/health/callback
AGENT_TOKEN_ENCRYPTION_KEY=replace-with-generated-fernet-key
AGENT_HEALTH_INTERVAL=43200
```

OAuth means Open Authorization.
The [Gmail guide](gmail.md#configure-the-service) includes the encryption-key command.
Use the existing key when another Google service already stores tokens.
The callback needs HTTPS except for HTTP on `localhost` or `127.0.0.1`.
For authorization on a phone, use a reachable HTTPS callback on the Theos server.
`localhost` on the phone points to the phone, not your server.
Gmail and Health can use the same Web client ID and secret, with separate callback URLs.

Health Connect and Apple HealthKit permissions belong to the mobile application.
They do not grant this server access to Google Health.

## Connect

These steps belong to each user, after the operator configures the service.
Users need no application credentials.

Before consent, sign into the Google Health mobile app with the Google account you intend to connect.
Complete its profile setup or Fitbit migration.
Google authorization can succeed without a linked Health profile, but subsequent data requests can fail.
See [Google's account linking procedure](https://developers.google.com/health/setup#link-google-health-before-oauth-consent).
Theos does not currently check `users.getIdentity` during the callback.

Browser users select **Connections > Google Health > Connect**, then **Continue sign-in**.
Return to the browser workspace after consent.
Ask for a Health summary refresh to check access.

For Telegram, complete `/start` and timezone setup in the bot's private chat first.

1. Send `/connect_health` in an allowed private Telegram chat.
2. Open the authorization link.
3. Grant all requested scopes.
4. Return to Telegram after the callback succeeds.
5. Send `/health_refresh` to request an import.
6. Send `/health_summary` to read the saved result.

The requested scope suffixes are:

| Scope prefix | Required suffix |
| --- | --- |
| `https://www.googleapis.com/auth/googlehealth.` | `activity_and_fitness.readonly` |
| Same prefix | `health_metrics_and_measurements.readonly` |
| Same prefix | `sleep.readonly` |
| Same prefix | `nutrition.readonly` |
| Same prefix | `nutrition.writeonly` |

The callback checks a single-use state, its expiry, and a Proof Key for Code Exchange (PKCE) verifier.

If the operator adds permissions, connect again to grant the additional access.
Saving scopes in Google Console does not change an existing account grant.

The current connector requires all five scopes.
It has no separate switch for read-only account consent.
A successful connection lets the scheduler queue historical meals that lack export markers.
It also queues future meal changes for export.

## Imports

The import reads the previous seven days.
It reads every result page and saves normalized daily summaries only after all required reads complete.
A partial import does not replace the last complete summary.
The default background interval is 43,200 seconds, or 12 hours.
Missing source metrics remain unavailable.

Manual refresh and background imports use the same service.
Browser and private Telegram sessions receive configured Health account tools.
Groups and terminal sessions receive no Health account tools.
The service stores normalized summaries rather than complete raw response bodies.

## Meal exports

A local meal change and its export intent commit in one SQLite transaction.
Remote failure does not remove the local meal.
The export worker handles saves, edits, and deletions in order.
It uses named remote records and saved operation IDs to inspect uncertain outcomes.

Historical export markers belong to the local owner and meal.
They are not a separate cursor for each remote Google account.
Changing the connected Google account does not automatically reset those markers.
Check existing export state before an account change.

## Export status and retries

Ask the assistant for `get_meal_sync_status` to inspect recent export jobs.

| Status | Meaning |
| --- | --- |
| `pending` | Job waits for execution |
| `running` | Worker claimed the job |
| `reconcile` | Worker must inspect or continue remote work |
| `completed` | Job finished |
| `failed` | Job reached its failure limit |
| `cancelled` | Local account disconnection cancelled the job |

The worker stops retrying after five failed attempts.
Earlier incomplete jobs block later jobs for the same owner and kind.

1. Correct the service or account problem.
2. Ask the assistant to run `retry_meal_sync` for failed nutrition jobs.
3. Read `get_meal_sync_status` again.
4. Check the remote record if an outcome remains uncertain.

`backfill_nutrition` queues meals without a local backfill marker.
It does not reset existing markers.
Do not log a meal again to retry its export.
A manual summary refresh does not clear a failed scheduled import job.
There is no dedicated command to retry failed import jobs.
Such failures require operator review of the saved job state.

## Disconnect

Send `/disconnect_health` from the private chat.
The application removes local credentials and pending authorization state.
It cancels unfinished Health jobs and attempts remote revocation.
Local meals and saved summaries remain in SQLite.
Remote nutrition records remain in Google Health.
An external request already in progress can still finish.

Source: [Health service](../src/theos/services/health/) and [OAuth service](../src/theos/services/google/oauth.py).
The [live checklist](runtime/acceptance.md#live-service-checks) still requires real account and nutrition contract checks.
