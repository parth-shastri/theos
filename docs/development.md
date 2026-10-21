# Development

## Requirements

Use Python 3.12 or later and uv.
The container uses Python 3.13.
The application uses `fcntl` for its process lock, so local execution needs a compatible Unix environment.
Use Docker on other hosts.
The frontend requires Node.js 24.18.0 and npm.

## Local application

1. Install the locked dependencies.

   ```sh
   uv sync --locked --extra server --extra terminal
   ```

2. Copy the minimal settings if `.env` does not exist.

   ```sh
   cp .env.minimal .env
   chmod 600 .env
   ```

3. Set `AGENT_NAME`, the browser credentials, and `AGENT_FRONTEND_SECRET` in `.env`.
4. Set `AGENT_WEB_URL=http://127.0.0.1:3000`.
5. Set `AGENT_PROVIDER=fake` for a local run without model calls.
6. Start the server.

   ```sh
   uv run --no-sync python -m theos.server
   ```

The fake provider returns a fixed response and does not exercise tools.
A real provider needs its credential in `AGENT_API_KEY`.
The API address is `http://127.0.0.1:8080`.
The API does not serve the browser page or frontend assets.

## Next.js frontend

1. Copy `web/.env.example` to `web/.env.local`.
2. Set a random service secret of at least 32 characters in both environment files.
3. Use `AGENT_FRONTEND_SECRET` for Python and `THEOS_FRONTEND_SECRET` for Next.js.
4. Set `AGENT_WEB_URL=http://127.0.0.1:3000` in both files.
5. Keep `AGENT_NAME` the same in both files.
6. Install and start the frontend.

   ```sh
   npm ci --prefix web
   npm --prefix web run dev
   ```

7. Open `http://127.0.0.1:3000`.

Next.js reads `THEOS_API_URL` only on the server.
Use the private API origin. Do not add `NEXT_PUBLIC_` to service secrets or API credentials.
The browser sends requests to the Next.js origin, so no cross-origin cookie or CORS configuration is needed.
Telegram pairing and account callbacks use the frontend's public HTTPS origin.

React components own the workspace content and interactions.
`web/src/state/WorkspaceContext.jsx` owns authenticated requests, navigation, and conversation actions.
`web/src/state/chat.js` converts saved history and ordered stream events into immutable conversation state.
`web/src/components/Messages.jsx` renders messages, statistics, tool disclosures, downloads, and approvals.
`web/src/components/Composer.jsx` owns drafts, attachments, command suggestions, and message-mode menus.
`web/src/components/Markdown.jsx` sanitizes Markdown and renders React elements, including code-copy controls and table regions.
The voice hook owns recording resources. Message components own speech playback resources.
Native browser effects retain focus, scrolling, dialogs, popovers, viewport measurement, and glass rendering.
The stylesheet and visual assets remain independent of the state migration.

For a production build:

```sh
npm --prefix web run build
npm --prefix web start
```

The build copies public assets and compiled chunks into the standalone output.
The default production port is 3000. `PORT` and `HOSTNAME` select its listener.
See the [Next.js authentication guide](https://nextjs.org/docs/app/guides/authentication) and [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

Start the terminal UI with `uv run --no-sync theos`.
The installed `theos` command also opens this UI.
Read the [terminal guide](terminal.md) for installation, local profiles, settings, and saved conversations.
The terminal and HTTP server each require exclusive access to their data directory.

## Docker development

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

Compose starts `web` and `theos` as separate services.
The frontend host port is 8080. The API host port is 8081 and binds to loopback by default.
The development file mounts the four Python source packages into the API container.
Restart the service after Python changes.
Rebuild the image after dependency changes.
The overlay does not enable automatic reload or Compose Watch.
It retains the host binding from the base configuration.

## Quality checks

Run the deterministic checks after an implementation change:

```sh
uv run --no-sync ruff check src/theos tests/app
uv run --no-sync ruff format --check src/theos tests/app
uv run --no-sync pytest -q
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
uv build
```

Browser acceptance runs against the two started services with a fake provider and disposable data:

```sh
THEOS_E2E_URL=http://127.0.0.1:3000 npm --prefix web run test:browser
```

Use the preview account from the CI workflow or set `THEOS_E2E_TOKEN` to a disposable account token.
The browser checks cover 320, 390, 768, and 1280 pixel widths in both themes.
They exercise cookie login, reload, logout revocation, CSRF rejection, streamed chat, menus, and workspace navigation.

The default pytest selection excludes tests marked `live`.
The [acceptance guide](runtime/acceptance.md) lists live checks and recorded results.
The [workflow](../.github/workflows/theos.yml) checks Python 3.12 and 3.13, all owned browser JavaScript, wheel imports, the lightweight client, Compose, and containers on five Linux architectures. An explicit extended run adds IBM Z and RISC-V.
AMD64 and ARM64 run natively; 386, ARMv7, and PPC64LE run under QEMU, as do the two extended targets.
Each container exercises native libraries, CPU word size, authenticated chat, and restart persistence.
It also validates workflows and scans Git history for secrets.
Read [Git and releases](releases.md) for branch and tagging procedures.
The container checks use the fake provider and disposable state.

## Add or change a tool

1. Read [project memory](../MEMORY.md) before changing the implementation plan.
2. Find the owning service in the [code guide](code-structure.md).
3. Put the callable in that service under `src/theos/services`.
4. Bind the authenticated owner when constructing the tool.
5. Register the tool in `runtime/tools.py` or the appropriate service collector.
6. Add approval rules for sensitive actions in `runtime/approvals.py`.
7. Check ownership, service failure, and uncertain outcomes with relevant tests.
8. Update the [tool catalog](tool-catalog.md) and service guide.
9. Record new project decisions in `MEMORY.md`.

Keep provider and protocol rules inside the owning service.
Keep generic harness behavior under `src/harness`.
Transport modules handle authentication and delivery.
They do not own service records or external protocols.
Preserve provenance manifests and the project's root license. Do not restore standalone upstream license files or source attribution notices.

## Maintain documentation

The [documentation map](documentation-map.md) is the navigation index.
The repository contains Markdown guides and local diagram previews.
It does not configure a documentation publishing service.

1. Check commands against the current source and environment samples.
2. Use Simplified Technical English for prose and procedures.
3. Embed the existing PNG diagrams where they explain the topic.
4. Label planned framework components explicitly.
5. Use the Excalidraw MCP for diagram edits.
6. Keep editable sources, element files, and previews in sync.
7. Use Excalidraw font family `1` for diagram text.
8. Check local links and the modified prose before delivery.

Read the [diagram library](architecture/README.md) for source files and preview commands.
