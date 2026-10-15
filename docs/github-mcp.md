# Connect GitHub accounts

Theos uses the official remote GitHub MCP server.
It does not implement a second copy of the provider's API tools.
This first implementation exposes reviewed read tools only.
Authenticated provider acceptance remains pending.

## Configure the deployment

Register a GitHub App with the exact callback URI.
Use its OAuth client ID and client secret, not its numeric app ID or signing key.
Grant read access to repository contents, issues, pull requests, and Actions as needed.
Install the app on the selected repositories before the user authorizes it.
The default scope list is empty because GitHub App permissions belong to the app registration.
OAuth Apps can use an explicit scope list, subject to organization policies.
GitHub also receives the read-only header and selected toolsets.

1. Register https://<theos-host>/oauth/github/callback with the provider.
2. Set AGENT_GITHUB__CLIENT_ID in the private deployment environment.
3. Set AGENT_GITHUB__CLIENT_SECRET in that environment.
4. Set AGENT_GITHUB__REDIRECT_URI to the exact registered URI.
5. Set AGENT_TOKEN_ENCRYPTION_KEY to the deployment's valid Fernet key.
6. Restart Theos after the settings change.

HTTP callbacks are allowed only on localhost or 127.0.0.1 for development.
The callback must reach the deployment that started authorization.
A localhost callback on another computer will not reach a remote Theos server.
Keep secrets out of shared environment samples.

The optional AGENT_GITHUB__SCOPES setting accepts a JSON list.
Default scopes: [].
The adapter checks returned scopes before saving the initial grant.
Tokens and authorization state remain bound to the configured client and endpoint.

## Connect an account

1. Open **Connections > GitHub** in an authenticated browser workspace.
2. Select **Connect**.
3. Open the returned sign-in link.
4. Complete the provider's account authorization.
5. Return to the workspace after the callback succeeds.

Private Telegram users can use /connect_github or /github.
They complete the same browser authorization and return to their private chat.
Connected terminal clients share the authenticated browser owner's access.
Groups and standalone terminal identities receive no account tools.

This release stores one GitHub connection per Theos owner.
Reconnect replaces that owner's grant only after a successful exchange.
Failed or canceled consent preserves the earlier connected grant.
Multiple accounts or workspaces need a later storage change.

## Available tools

The official endpoint is https://api.githubcopilot.com/mcp/.

The reviewed allowlist contains 23 read-tool identifiers.
Only tools returned by authenticated discovery can appear in the conversation.
See the [inventory](connectors/github-tools.json) and [service module](../src/theos/services/github/__init__.py).

Theos prefixes tool names with github_ unless that prefix already exists.
Each tool takes an arguments object that matches its discovered JSON schema.
The model receives that schema with the tool description.
The adapter rejects invalid arguments before a remote action starts.
Unknown tools and write tools remain unavailable.
GitHub-style method tools also require a reviewed read method.

The adapter pages through the complete discovery catalog.
It preserves remote read responses as owner-bound source records.
Large responses return a first page and a source_id.
The source_read tool retrieves later pages.
The adapter does not fetch external resource links automatically.

## Disconnect and recovery

Use **Disconnect** in Connections or /disconnect_github in private Telegram.
Disconnection removes local tokens and pending authorization state.
It also closes that owner's remote session.
Revoke the app in GitHub to end the provider's authorization.
Theos reports that local disconnection does not confirm upstream revocation.

Encrypted credentials survive application restart.
Token refresh runs under the same owner lock as disconnection.
A changed client, endpoint, or scope list requires authorization again.
The adapter does not repeat failed calls automatically.
An optional connector outage does not prevent ordinary chat.

## Implementation and acceptance

The adapter uses existing mcp, httpx, cryptography, and jsonschema dependencies.
No new provider SDK, Node.js proxy, or local MCP server is required.
Provider configuration stays in services/github/.
Shared account code stays in services/mcp_accounts/.
The existing runtime owns journals, source records, access checks, and delivery.

Focused tests cover OAuth ownership, callback replay, encrypted restart access, discovery, schema rejection, and transport boundaries.
They also cover durable source paging, optional-service failure, and private Telegram commands.
The shared wire test uses the real MCP client against a mock HTTP transport.
These tests do not prove production provider access.

Live acceptance must check account consent, a complete read, permission removal, restart, and disconnection.
See [acceptance](runtime/acceptance.md) for the recorded checks.
The [official integration guide](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md) describes external setup.
The local logo comes from Simple Icons 11.15.0 under CC0-1.0.
Its source and license links accompany the asset in the provider notice.
