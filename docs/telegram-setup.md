# Telegram setup

Telegram is the first Theos transport.
The application polls for updates through outbound HTTPS.
It does not need a public webhook or an inbound Telegram port.

## Create the bot

1. Open the verified BotFather account in Telegram.
2. Send `/newbot`.
3. Choose the bot display name and username.
4. Save the token in your private `.env` file.

The Telegram username and display name are separate from `AGENT_NAME`.
The configured assistant name appears in greetings and model instructions.
Treat the bot token as a password.

## Configure access

```dotenv
AGENT_NAME=Theos
AGENT_TELEGRAM_TOKEN=replace-me
AGENT_TELEGRAM_ACCESS_CODE=replace-with-your-deployment-password
AGENT_TELEGRAM_USERS=[]
AGENT_TELEGRAM_MAX_USERS=50
AGENT_TELEGRAM_CHATS=[]
AGENT_WEB_URL=https://theos.example.com
```

A nonempty token enables polling.
`AGENT_WEB_URL` supplies the HTTPS origin for browser sign-in links.
Make that address reachable before onboarding users. An empty value disables automatic web links.
An empty sender allowlist lets users register without manual ID configuration.
When an access code exists, users send `/start <access-code>` in a private chat.
Without an access code, `/start` permits public registration within the user limit.
Set `AGENT_TELEGRAM_USERS` to numeric sender IDs to restrict registration and chat access.
The bot reads sender IDs from Telegram and saves authorization in SQLite.
Completed users can connect Gmail, Google Health, and Zepto from their private chat.
For a hosted service, users need no Google application credentials.
The operator configures those credentials once for the deployment.
For self-hosting, each installation owner supplies their own credentials.
See [deployment options](DEPLOYMENT.md#choose-a-deployment-option).
Each Zepto user signs in through the Zepto MCP OAuth flow.
Keep the access code in the deployment's private `.env` file.
Changing the code requires users to authorize again, but preserves profiles and enrollment slots.
The bot removes code arguments before saving inbox updates and attempts to delete the code message from Telegram.

Groups require an enrolled sender and an allowed chat ID.
A configured sender allowlist also applies to groups:

```dotenv
AGENT_TELEGRAM_USERS=[123456789]
AGENT_TELEGRAM_CHATS=[-1001234567890]
```

Group senders and topics have separate conversation identities.
They do not receive the private sender records or Google and Zepto account tools.
BotFather privacy settings also affect which group messages Telegram delivers to the bot.

## User onboarding and limit

1. Send `/start` in a private chat with the bot.
   If prompted, send `/start <access-code>` with the deployment password.
2. Send the name you want Theos to use.
3. Send your timezone, such as `Asia/Kolkata` or `UTC`.
4. Send a short message after the setup confirmation.

The bot asks, "What should I call you?"
It saves your answer as your private display name and supplies it to the model on each turn.
Names can contain up to 200 characters. The bot removes extra whitespace.
During the name step, `/skip` accepts your saved name or Telegram name when available.
Without a saved name, the bot asks for a name before it continues.
During the timezone step, `/skip` accepts the default timezone saved at registration.
The bot validates the timezone before it enables commands, media, and model turns.
You can ask the assistant to change your display name or timezone later.
Conversation resets retain your display name.

Telegram enrollment does not grant administrator access.
The deployment operator configures their administrator account through `AGENT_USERS` and `AGENT_ADMINS`.
The first enrolled Telegram user receives ordinary access, like later users.
After setup, **Open Theos** opens the browser confirmation flow when `AGENT_WEB_URL` is configured.
After profile setup, Theos offers buttons for configured accounts that are not connected.
Gmail and Zepto have direct connection buttons. Google Health remains optional.
Use **Skip for now** to continue without connecting accounts. The same preference applies in browser onboarding.
Connections and `/help` remain available later. A configured web URL also enables browser access.
Confirm the matching code in your private Telegram chat before the browser receives access.
Save the personal token shown in the browser for future sign-in.
Send `/web` for another link or `/web revoke` to end all generated browser access.
See [browser access](browser.md#open-the-web-ui-from-telegram) for expiry, token rotation, and sign-out behavior.
Encryption setup is deferred. This flow does not encrypt personal content.

The default limit is 50 unique Telegram users per database.
`AGENT_TELEGRAM_MAX_USERS` accepts limits from 1 to 50.
An incomplete setup reserves one slot.
Repeated `/start` commands, conversation resets, groups, and topics do not consume additional slots.
Browser users do not consume Telegram slots.
At capacity, new users receive a registration-full message.
Registered users keep access at capacity.

SQLite retains registration and setup state across restarts.
Existing private Telegram users retain their preferences and access after the database migration.
They count toward the limit once per sender.
If existing users exceed the configured limit, the bot preserves them and refuses new registrations.

## Start and check

1. Complete the model settings in the [configuration guide](base-infra/environment-variables.md#models-and-cost-estimates).
2. Recreate the Compose service.

   ```sh
   docker compose config --quiet
   docker compose up -d --force-recreate
   ```

3. Send `/start` from a private account that meets the access settings.
4. Complete preferred-name and timezone setup.
5. Send a short message.
6. Check the configured assistant name and model response.

Run only one poller for a bot token.
The [acceptance checklist](runtime/acceptance.md) distinguishes mock workflows from live Telegram checks.

## Commands

| Command | Action |
| --- | --- |
| `/start [access-code]` | Authorize, register, resume incomplete setup, or show the greeting after setup |
| `/skip` | Accept the saved name or default timezone for the current setup step |
| `/web` | Open a private browser sign-in link after enrollment |
| `/web revoke` | Revoke all generated browser tokens and device sessions without deleting personal data |
| `/help` | Show the greeting and command summary after setup |
| `/new`, `/reset` | Reset conversation history and pending approvals |
| `/resume` | Continue an interrupted turn or a turn that reached its call limit |
| `/model NAME` | Select an allowed model |
| `/reasoning LEVEL`, `/thinking LEVEL` | Select `default`, `none`, `low`, `medium`, or `high` |
| `/settings` | Show model, reasoning effort, and session ID |
| `/connect_gmail`, `/gmail` | Create a Gmail authorization link |
| `/disconnect_gmail` | Disconnect Gmail |
| `/connect_health`, `/health` | Create a Google Health authorization link |
| `/health_summary` | Read the last saved Health summary |
| `/health_refresh` | Import a new Health summary |
| `/disconnect_health` | Disconnect Health and cancel pending account jobs |
| `/connect_zepto`, `/zepto` | Connect your Zepto account from this private chat |
| `/disconnect_zepto` | Remove your saved Zepto credentials from Theos |
| `/zepto_finish <url>` | Finish sign-in when the browser returns to localhost |

`/model` without an accepted model name lists the available models.
Model choices come from `AGENT_ALLOWED_MODELS`, or only `AGENT_MODEL` when the list is empty.
The application does not discover model capabilities automatically.
A selected model must support the requested reasoning effort.

A reset keeps personal records and files.
Google account commands work only in private chats.
Disconnect commands run directly without a separate approval button.

## Reply formatting

Assistant replies use Telegram formatting for emphasis, links, and code.
Headings become bold text. Lists and tables become readable text rows.
Long replies split into messages while keeping formatting and emoji intact.
The renderer reparses partial Markdown as a reply streams.
Commands and approval reviews remain literal text.
The assistant avoids em dashes across transports, including saved replies and generated titles.

## Media and voice

Photos, documents, audio files, and voice notes enter the private file catalog.
Valid images can enter the model request when the selected model accepts images.
Albums group pending items after 1.5 seconds without another received item.
A late item can create another turn.

Voice notes require a configured transcription service.
The transport saves the audio and sends its transcript through the normal turn path.
Generated audio returns through Telegram audio delivery.
Other generated files return as documents.
See [files and voice](files-and-voice.md) for endpoints and limits.

## Progress and approvals

The transport edits a progress message while the turn runs.
It shows tool progress and splits long text across messages.
Sensitive calls receive **Approve** and **Deny** buttons.
A large approval preview also arrives as `approval-review.txt`.
Read the full preview before deciding.

![Telegram checkpoint order](architecture/theos-telegram.png)

The current transport saves inbound updates before dispatch.
It records uncertain delivery instead of repeating the model turn.
The diagram describes checkpoint order and does not establish a complete reply outbox.
See [operations](operations.md#recover-interrupted-work) for interrupted turns.

## Problems

If no reply arrives, check the token, sender allowlist, model settings, and outbound network access.
For groups, also check the chat allowlist and bot privacy settings.
Use the [troubleshooting guide](troubleshooting.md#telegram-does-not-respond) for the full procedure.

Source: [Telegram transport](../src/theos/transports/telegram/).
