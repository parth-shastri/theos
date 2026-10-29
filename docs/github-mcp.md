# Connect GitHub accounts

Theos uses the official remote GitHub MCP server.
It does not implement a second copy of the provider's API tools.
This first implementation exposes reviewed read tools only.
Authenticated provider acceptance remains pending.

## Configure the deployment

Register a GitHub App with the exact callback URI.
Use its OAuth client ID and client secret, not its numeric app ID or signing key.
Grant read access to Contents, Issues, Pull requests, Actions, Checks, and Commit statuses as needed.
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

For this local Docker test, register http://localhost:8080/oauth/github/callback.
Keep expiring user tokens enabled. Leave user authorization during installation off.
Enable webhooks for event notifications as described below. The OAuth flow needs no app private key.
HTTP callbacks are allowed only on localhost or 127.0.0.1 for development.
The callback must reach the deployment that started authorization.
A localhost callback on another computer will not reach a remote Theos server.
Keep secrets out of shared environment samples.

The optional AGENT_GITHUB__SCOPES setting accepts a JSON list.
Default scopes: [].
The adapter checks returned scopes before saving the initial grant.
Tokens and authorization state remain bound to the configured client and endpoint.

## Event notifications

Enable **Webhooks → Active** in the GitHub App settings.
Use this production webhook URL after deploying the receiver:

```text
https://theos.parth-shastri.com/webhooks/github
```

GitHub cannot deliver a webhook to localhost. For local testing, use an HTTPS tunnel to port 8080.
Set the app webhook URL to https://<test-host>/webhooks/github for that test.
The OAuth callback remains /oauth/github/callback and has a separate purpose.

Set AGENT_GITHUB_WEBHOOK_SECRET to a dedicated random value of at least 32 characters.
Copy that same value into the app's webhook **Secret** field. Keep SSL verification enabled.
A secret was generated in the ignored local .env for this development session. Do not commit it.

Subscribe to these app events:

| GitHub event | Alerts selected by Theos |
| --- | --- |
| Issues | Assignment to you and new direct @mentions in issue bodies |
| Issue comment | New direct @mentions in issue or PR comments |
| Pull request | Assignment, direct review requests, and new direct @mentions |
| Pull request review | Direct @mentions in submitted review text |
| Pull request review comment | Direct @mentions in review comments |
| Workflow run | Failed, timed-out, or action-required runs you triggered |

Team mentions and team review requests are not included. Self-authored issue and PR activity does not notify its author.
The existing repository read permissions cover these events. No account, organization, or enterprise permissions are added.

After connecting GitHub, enable **Event notifications → Notify me in Theos** in Connections.
Alerts appear in the private Connections inbox and the existing conversation notification area.
Marking an alert read removes it from the conversation notification area.
For private Telegram alerts, connect GitHub from that Telegram identity and send /github_notifications on.
Use /github_notifications off to stop them. A browser identity is never matched to a Telegram user by name.
Existing verified Telegram-owned browser sessions can also enable the Telegram checkbox.

The receiver verifies X-Hub-Signature-256 over the original bytes before parsing.
It accepts up to 1 MiB, commits encrypted pending payloads, and acknowledges without calling the model.
X-GitHub-Delivery deduplicates redelivery. Reusing an ID with different content is rejected.
The background worker matches the opted-in GitHub identity and checks current repository access with its user token.
These native REST checks use GET /user and GET /repositories/{id}. They do not add model tools.
Reconnection and disconnection disable the previous subscription. No pending alert crosses a subscription revision.

Pending payloads expire after seven days. Processed payload content is discarded immediately.
Delivery IDs and private inbox records expire after 30 days.
Telegram sends are claimed before delivery. A failed or interrupted send remains uncertain and is not repeated automatically.
The raw event cannot start a model turn or execute tools. Live delivery still requires a public route to the deployed receiver.

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
Small responses remain inline. Oversized reads use the current provider result staging service.
With a sandbox available, results up to 1 MiB receive a temporary result_file path.
Use run_command to inspect selected sections. These files are not durable workspace checkpoints.
If staging is unavailable, the tool returns a bounded preview and requests a narrower read.
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
The existing runtime owns journals, result staging, access checks, and delivery.

Focused tests cover OAuth ownership, callback replay, encrypted restart access, discovery, schema rejection, and transport boundaries.
They also cover bounded results, temporary staging, setup cancellation, optional-service failure, and private Telegram commands.
The shared wire test uses the real MCP client against a mock HTTP transport.
These tests do not prove production provider access.

Live acceptance must check account consent, a complete read, permission removal, restart, and disconnection.
See [acceptance](runtime/acceptance.md) for the recorded checks.
The [official integration guide](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md) describes external setup.
The local logo comes from Simple Icons 11.15.0 under CC0-1.0.
Its source and license links accompany the asset in the provider notice.
