# Use the terminal UI

The `theos` command opens the terminal user interface (UI).
It uses the installed package and needs no module target.
The terminal can connect to a deployment or run a standalone local runtime.
Connected terminals use protocol version 2 for answer replacement.
Update the deployment and client together when installing this change.
Connected mode shares the browser user's conversations, tools, settings, approvals, and usage.
Standalone mode retains its own terminal owner and SQLite storage.

## Connect to a deployment

Install the client on your computer or on the VPS where you use SSH.
The deployment must run the matching server version.

1. Install the client from the codebase.

   ```sh
   uv tool install --editable '.[client]'
   ```

2. Start the client with the same URL you use for browser access.

   ```sh
   theos --server http://127.0.0.1:8080
   ```

3. Enter your browser login token at the hidden prompt.
4. Choose a saved conversation or use `/new`.

For direct Tailscale access, use your deployment's Tailscale hostname and port.
For a tunnel, use its local forwarded address. The client needs no special Tailscale integration.
For SSH, install the client on the VPS and run it against the deployment's localhost port.
The server image contains the server dependencies. Install the client on the host for an SSH terminal session.

The server owns SQLite, model calls, account tools, approvals, and scheduling.
The client opens no local database and starts no scheduler or Telegram poller.
Its token selects the same owner as browser login. New client conversations appear in the browser.
Existing standalone terminal identities remain separate. Connected mode does not migrate or link them.

Without an initial prompt, connected mode opens the shared conversation picker when saved conversations exist.
Remote conversations have no local directory filter. Archive state applies to the terminal picker only.
Renamed titles appear in both interfaces. Reload either interface to see changes made by the other.
One conversation can have one active turn, regardless of which interface started it.

Use a private configuration file to save the connection settings.
The [client sample](../.env.client.example) contains only the URL and browser token.

```dotenv
AGENT_SERVER_URL=http://your-vps:8080
AGENT_SERVER_TOKEN=replace-with-your-browser-token
```

```sh
chmod 600 /path/to/client.env
theos --config /path/to/client.env
```

`--server` overrides the saved URL. `--token-file /path/to/token` overrides the saved token.
The token file contains only the browser token. The CLI does not accept a token argument.
Set `AGENT_SERVER_URL` in the normal terminal configuration to make plain `theos` use the deployment.
Use `--local` to select standalone mode even when a server URL is configured.
An authentication or connection failure never falls back to standalone mode.
Remote mode rejects `--owner` and `--data-dir`. The deployment controls both identity and storage.

| Connected command | Action |
| --- | --- |
| `/settings` | Edit the shared model, reasoning effort, and supported generation parameters |
| `/model`, `/reasoning` | Show supported options. Select with arrows and Enter or Tab, then Enter to save |
| `/usage` | Open conversation and user cost, request, and token tables |
| `/continue` | Continue saved work after an interruption |

The commands in the table below also remain available.
`/thinking` changes trace visibility. `/reasoning` changes the model's reasoning effort.
Generation controls live in `/settings`. There is no `/generation` command.
Voice recording and account consent remain browser features.
Connected chat can use the authenticated user's configured account tools with the server's normal approval policy.

Closing the client or losing its connection does not cancel server work.
Reconnect and use `/reload` to inspect the saved result before repeating a request.
Use `/continue` only when saved work needs continuation.
Requests, steering, and approval submissions have no automatic retry.
The server continues scheduling while no client is connected.

The `client` extra installs HTTPX, Pydantic Settings, Rich, and Textual.
It does not install model SDKs, FastAPI, or optional service clients.

## Install and start standalone mode

1. Install the command from the codebase.

   ```sh
   uv tool install --editable '.[terminal]'
   ```

2. If your shell cannot find `theos`, update its tool path.

   ```sh
   uv tool update-shell
   ```

3. Open a new shell after a path change.
4. Set `AGENT_API_KEY` in your private `.env` file.
5. Start the terminal UI.

   ```sh
   theos --local
   ```

The `terminal` extra includes the application dependencies, Rich, and Textual.
A wheel installation can use `pip install '/path/to/theos.whl[terminal]'`.
An editable installation reads source changes from the codebase.

The default model remains `gpt-6-luna` through OpenAI Responses.
Set `AGENT_PROVIDER=fake` for an offline response without model calls.
Set `AGENT_NAME` to change the displayed assistant name.

For development inside the project environment, use `uv run --extra terminal theos`.
The HTTP server starts separately through `python -m theos.server`.
One application process can own each data directory.
Stop that process before another process opens the same directory.

## Standalone settings and storage

The command searches for `.env` in the current directory, then the editable codebase, then `~/.config/theos/.env`.
Environment variables take precedence over file settings.
Use `--config` to select another file.

```sh
theos --config /path/to/private.env
```

Without `AGENT_DATA_DIR`, the terminal stores its data under `~/.theos`.
A relative `AGENT_DATA_DIR` refers to the selected configuration directory.
Without a configuration file, a relative path refers to the current directory.
Use `--data-dir` to select a different directory.

```sh
theos --data-dir /path/to/terminal-data
```

The local profile defaults to your operating system username.
The command saves its owner as `terminal:<username>`.
Use `--owner <name>` to select another local profile.
Local filesystem access controls these profiles.
They are separate from browser and Telegram identities.
Gmail, Google Health, and Zepto account tools require browser or private Telegram conversations.
Standalone terminal sessions receive no account tools.

## Conversations and commands

Each standalone `theos` launch creates a new conversation.
Use `--session <id>` to open or create a named conversation.
Use `--resume` to open the saved conversation picker.
Use `--resume <id>` to resume one conversation directly.

```sh
theos --session daily
theos --resume
theos --resume daily
```

| Command or key | Action |
| --- | --- |
| `/help` | Show commands and keyboard controls |
| `/new` | Create a new conversation and clear the screen |
| `/resume` | Search, sort, and filter saved conversations |
| `/rename <title>` | Set the conversation title |
| `/reload` | Read the saved transcript again |
| `/status` | Show a grouped status panel with the run state, model, session, workspace, and latest-turn counters |
| `/permissions` | Show the approval policy |
| `/thinking`, Ctrl+R | Expand or collapse reasoning |
| `/tools`, Ctrl+T | Expand or collapse tool details |
| `/clear`, Ctrl+L | Clear the visible transcript |
| `/quit`, Ctrl+C | Exit and cancel active work |

The status panel wraps long values to fit the terminal.
It retains waiting and failed states until another turn or session changes them.
Latest-turn counters cover events observed by this client. They reset when you change sessions.
Connected `/usage` shows saved conversation and user totals.

The conversation picker stores directory and archive state.
Ctrl+A archives or restores its selected conversation.
SQLite retains messages, titles, timestamps, compaction memory, approvals, and tool checkpoints across restarts.

## Images, steering, and approvals

Use `@` to choose a local image.
Use Ctrl+V to attach an image from the clipboard.
You can also supply initial input from the command line.

```sh
theos --prompt "Describe this image" --image /path/to/image.png
```

Image attachments enter the owner's private file catalog before the model request.
Generated file notices show the local file path.
The command never executes a generated file.

Input sent during a turn becomes steering for the next model boundary.
On interruption, the runtime saves unconsumed steering in the transcript.
It does not repeat external actions automatically.

Protected tools show the saved arguments and action preview.
Choose Allow once or Deny.
The runtime binds decisions to the saved call and arguments.
Approvals expire after 15 minutes.
Resuming a conversation restores pending approval prompts before a new model call.

The standalone terminal runs the application scheduler while it remains open.
Reminders and scheduled task results appear as notices.
Use `/reload` to read a scheduled turn's complete saved transcript.
Work due during downtime follows the existing scheduler recovery rules at the next start.
