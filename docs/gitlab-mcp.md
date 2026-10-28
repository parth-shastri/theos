# Connect GitLab accounts

Theos uses the official remote GitLab MCP server.
It does not implement a second copy of the provider's API tools.
This first implementation exposes reviewed read tools only.
Authenticated provider acceptance remains pending.

## Configure the deployment

Register an OAuth application on the configured instance with the mcp scope.
For the GitLab MCP application, clear the Confidential checkbox.
Enable the instance's MCP server or the required group setting.
The default instance is https://gitlab.com.
AGENT_GITLAB__INSTANCE_URL selects another HTTPS origin.
One deployment uses one configured instance in this implementation.
Changing the instance requires account authorization again.
Legacy REST tokens cannot replace the MCP OAuth grant.

The server version controls available tools.
The adapter accepts reviewed current and legacy read names only when discovery returns them.
Missing tools remain unavailable. The adapter does not switch silently to REST.

1. Register https://<theos-host>/oauth/gitlab/callback with the provider.
2. Set AGENT_GITLAB__CLIENT_ID in the private deployment environment.
3. Set AGENT_GITLAB__CLIENT_SECRET to the application's generated secret.
4. Set AGENT_GITLAB__REDIRECT_URI to the exact registered URI.
5. Set AGENT_TOKEN_ENCRYPTION_KEY to the deployment's valid Fernet key.
6. Restart Theos after the settings change.

For this local Docker test, register http://localhost:8080/oauth/gitlab/callback.
HTTP callbacks are allowed only on localhost or 127.0.0.1 for development.
The callback must reach the deployment that started authorization.
A localhost callback on another computer will not reach a remote Theos server.
Keep secrets out of shared environment samples.

The optional AGENT_GITLAB__SCOPES setting accepts a JSON list.
Default scopes: ["mcp"].
The adapter checks returned scopes before saving the initial grant.
Tokens and authorization state remain bound to the configured client and endpoint.

## Connect an account

1. Open **Connections > GitLab** in an authenticated browser workspace.
2. Select **Connect**.
3. Open the returned sign-in link.
4. Complete the provider's account authorization.
5. Return to the workspace after the callback succeeds.

Private Telegram users can use /connect_gitlab or /gitlab.
They complete the same browser authorization and return to their private chat.
Connected terminal clients share the authenticated browser owner's access.
Groups and standalone terminal identities receive no account tools.

This release stores one GitLab connection per Theos owner.
Reconnect replaces that owner's grant only after a successful exchange.
Failed or canceled consent preserves the earlier connected grant.
Multiple accounts or workspaces need a later storage change.

## Available tools

The official endpoint is https://gitlab.com/api/v4/mcp.
Theos derives the endpoint from the configured origin for self-managed instances.
The reviewed allowlist contains 32 read-tool identifiers.
Only tools returned by authenticated discovery can appear in the conversation.
See the [inventory](connectors/gitlab-tools.json) and [service module](../src/theos/services/gitlab/__init__.py).

Theos prefixes tool names with gitlab_ unless that prefix already exists.
Each tool takes an arguments object that matches its discovered JSON schema.
The model receives that schema with the tool description.
The adapter rejects invalid arguments before a remote action starts.
Unknown tools and write tools remain unavailable.

The adapter pages through the complete discovery catalog.
Large responses use the shared temporary result-file service.
The model can inspect selected sections with run_command.
A staged response does not establish complete provider pagination.
The adapter does not fetch external resource links automatically.

## Disconnect and recovery

Use **Disconnect** in Connections or /disconnect_gitlab in private Telegram.
Disconnection removes local tokens and pending authorization state.
It also closes that owner's remote session.
Revoke the app in GitLab to end the provider's authorization.
Theos reports that local disconnection does not confirm upstream revocation.

Encrypted credentials survive application restart.
Token refresh runs under the same owner lock as disconnection.
A changed client, endpoint, or scope list requires authorization again.
The adapter does not repeat failed calls automatically.
An optional connector outage does not prevent ordinary chat.

## Implementation and acceptance

The adapter uses existing mcp, httpx, cryptography, and jsonschema dependencies.
No new provider SDK, Node.js proxy, or local MCP server is required.
Provider configuration stays in services/gitlab/.
Shared account code stays in services/mcp_accounts/.
The existing runtime owns journals, result staging, access checks, and delivery.

Focused tests cover OAuth ownership, callback replay, encrypted restart access, discovery, schema rejection, and transport boundaries.
They also cover bounded result staging, optional-service failure, and private Telegram commands.
The shared wire test uses the real MCP client against a mock HTTP transport.
These tests do not prove production provider access.

Live acceptance must check account consent, a complete read, permission removal, restart, and disconnection.
See [acceptance](runtime/acceptance.md) for the recorded checks.
The [official integration guide](https://docs.gitlab.com/user/model_context_protocol/mcp_server/) describes external setup.
The local logo comes from Simple Icons 11.15.0 under CC0-1.0.
Its source and license links accompany the asset in the provider notice.
