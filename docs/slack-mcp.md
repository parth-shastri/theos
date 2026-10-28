# Connect Slack accounts

Theos uses the official remote Slack MCP server.
It does not implement a second copy of the provider's API tools.
This first implementation exposes reviewed read tools only.
Authenticated provider acceptance remains pending.

## Configure the deployment

Register an internal Slack app or a Marketplace app.
Enable the Slack MCP server feature in that app.
An unlisted app cannot use the official MCP server.
Workspace administrator settings can prevent authorization.
The adapter uses Slack's user-token endpoints, not a bot token.
It uses confidential OAuth with a client secret and durable single-use state.
It does not enable Slack's public-client PKCE mode.
A Slack bot transport or event subscription is not required.

Default scopes cover public search, user search, public channel reads, and user profiles.
Private scopes include search:read.private, search:read.im, search:read.mpim, groups:history, im:history, and mpim:history.
Request only the private scopes needed by the intended conversations.
Private search needs matching search scopes and Slack's separate user consent.
Private history needs matching conversation scopes.
Additional file, canvas, list, and reaction reads need their respective scopes.
The adapter never grants scopes merely because a remote tool appears in discovery.

1. Register https://<theos-host>/oauth/slack/callback with the provider.
2. Set AGENT_SLACK__CLIENT_ID in the private deployment environment.
3. Set AGENT_SLACK__CLIENT_SECRET in that environment.
4. Set AGENT_SLACK__REDIRECT_URI to the exact registered URI.
5. Set AGENT_TOKEN_ENCRYPTION_KEY to the deployment's valid Fernet key.
6. Restart Theos after the settings change.

Slack requires HTTPS for registered callbacks, including local development.
Use an HTTPS endpoint that routes to this deployment for local OAuth tests.
The callback must reach the deployment that started authorization.
A localhost callback on another computer will not reach a remote Theos server.
Keep secrets out of shared environment samples.

The optional AGENT_SLACK__SCOPES setting accepts a JSON list.
Default scopes: ["search:read.public", "search:read.users", "channels:read", "channels:history", "users:read"].
The adapter checks returned scopes before saving the initial grant.
Tokens and authorization state remain bound to the configured client and endpoint.

## Connect an account

1. Open **Connections > Slack** in an authenticated browser workspace.
2. Select **Connect**.
3. Open the returned sign-in link.
4. Complete the provider's account authorization.
5. Return to the workspace after the callback succeeds.

Private Telegram users can use /connect_slack or /slack.
They complete the same browser authorization and return to their private chat.
Connected terminal clients share the authenticated browser owner's access.
Groups and standalone terminal identities receive no account tools.

This release stores one Slack connection per Theos owner.
Reconnect replaces that owner's grant only after a successful exchange.
Failed or canceled consent preserves the earlier connected grant.
Multiple accounts or workspaces need a later storage change.

## Available tools

The official endpoint is https://mcp.slack.com/mcp.

The reviewed allowlist contains 18 read-tool identifiers.
Only tools returned by authenticated discovery can appear in the conversation.
See the [inventory](connectors/slack-tools.json) and [service module](../src/theos/services/slack/__init__.py).

Theos prefixes tool names with slack_ unless that prefix already exists.
Each tool takes an arguments object that matches its discovered JSON schema.
The model receives that schema with the tool description.
The adapter rejects invalid arguments before a remote action starts.
Unknown tools and write tools remain unavailable.
GitHub-style method tools also require a reviewed read method.

The adapter pages through the complete discovery catalog.
Small responses remain inline. Oversized reads use the current provider result staging service.
With a sandbox available, results up to 1 MiB receive a temporary result_file path.
Use run_command to inspect selected sections. These files are not durable workspace checkpoints.
If staging is unavailable, the tool returns a bounded preview and requests a narrower read.
The adapter does not fetch external resource links automatically.

## Disconnect and recovery

Use **Disconnect** in Connections or /disconnect_slack in private Telegram.
Disconnection removes local tokens and pending authorization state.
It also closes that owner's remote session.
Revoke the app in Slack to end the provider's authorization.
Theos reports that local disconnection does not confirm upstream revocation.

Encrypted credentials survive application restart.
Token refresh runs under the same owner lock as disconnection.
A changed client, endpoint, or scope list requires authorization again.
The adapter does not repeat failed calls automatically.
An optional connector outage does not prevent ordinary chat.

## Implementation and acceptance

The adapter uses existing mcp, httpx, cryptography, and jsonschema dependencies.
No new provider SDK, Node.js proxy, or local MCP server is required.
Provider configuration stays in services/slack/.
Shared account code stays in services/mcp_accounts/.
The existing runtime owns journals, result staging, access checks, and delivery.

Focused tests cover OAuth ownership, callback replay, encrypted restart access, discovery, schema rejection, and transport boundaries.
They also cover bounded results, temporary staging, setup cancellation, optional-service failure, and private Telegram commands.
The shared wire test uses the real MCP client against a mock HTTP transport.
These tests do not prove production provider access.

Live acceptance must check account consent, a complete read, permission removal, restart, and disconnection.
See [acceptance](runtime/acceptance.md) for the recorded checks.
The [official integration guide](https://docs.slack.dev/ai/slack-mcp-server/) describes external setup.
The local logo comes from Simple Icons 11.15.0 under CC0-1.0.
Its source and license links accompany the asset in the provider notice.
