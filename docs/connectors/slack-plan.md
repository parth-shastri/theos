# Slack connector plan

Status: proposed, not implemented. Reviewed on 2026-10-15.
Branch: `feature/slack-connector`. Base: `origin/dev` at `8a4360f`.

## Tool evidence

The [official MCP guide](https://docs.slack.dev/ai/slack-mcp-server/) describes search, messages, files, canvases, profiles, and lists.
The separate [inventory](slack-tools.json) records all 38 Slack tools exposed in this Codex session.
That snapshot does not prove the same tools exist for a new Theos app or token.
No Slack messages, files, or private account data were read during this review.

| Area | Representative session tools | Initial scope |
| --- | --- | --- |
| Discovery | `slack_list_workspaces`, `slack_list_user_channels`, `slack_list_user_conversations` | Include when discovered |
| Search | `slack_search_public`, `slack_search_public_and_private`, `slack_search_channels`, `slack_search_users` | Include granted scopes |
| Conversation reads | `slack_read_channel`, `slack_read_thread`, `slack_read_user_profile`, `slack_list_channel_members` | Include |
| Content reads | `slack_read_file`, `slack_read_canvas`, `slack_read_list` | Later increment |
| Messages | `slack_send_message_draft`, `slack_send_message`, `slack_schedule_message` | Later increment |
| Message edits | `slack_edit_message`, `slack_delete_message`, `slack_add_reaction` | Later increment |
| Files | `slack_get_file_upload_url`, `slack_complete_file_upload` | Deferred |
| Other writes | Conversation membership, profiles, canvases, lists, reminders | Deferred |

Use these names as coverage references until authenticated discovery confirms the Theos catalog.
Do not assume an API equivalent exists for every session tool.
For example, a connector draft operation needs its own capability check.

## Complexity

These ratings are engineering estimates, not measured durations.

| Work | Complexity | Reason |
| --- | --- | --- |
| One internal workspace, read tools | Medium-high | User scopes, app identity, pagination, and thread completeness |
| Hosted distribution | High | Marketplace eligibility and workspace administrator settings |
| Multiple workspaces | High | Separate grants, identities, selection, and rate limits |
| Writes and uploads | High | Posting identity, message edits, scheduling, and multi-step effects |
| Full catalog | High | Different permissions, document formats, and workspace features |

Slack hosts `https://mcp.slack.com/mcp` over Streamable HTTP.
Its guide requires a registered app and permits internal or Marketplace apps.
Unlisted apps cannot use MCP.
It does not support Dynamic Client Registration.
These conditions change the earlier generic OAuth proposal.

Prefer official MCP for an eligible internal deployment.
Evaluate hosted distribution separately before promising broad account onboarding.
A Web API adapter is an explicit alternative with a separate scope and coverage review.
Do not use that alternative to bypass app eligibility requirements.

The [development guide](https://docs.slack.dev/ai/slack-mcp-server/developing/) describes app setup and MCP enablement.
Use the documented user-token endpoints and confidential OAuth client.
Request only scopes needed by the selected tools.
The [search announcement](https://docs.slack.dev/changelog/2026/02/17/slack-mcp) describes granular public, private, and direct-message search scopes.
The [legacy search method](https://docs.slack.dev/reference/methods/search.messages/) recommends Real-time Search.
Do not build a new search plan around legacy `search:read` alone.
Check private-search consent and revocation independently of token presence.

## Delivery steps

1. Check app eligibility, administrator settings, user authorization, and complete `tools/list` results.
2. Save sanitized tool schemas and compare them with the session inventory.
3. Add `services/slack/` with authentication, client, and tool modules.
4. Add encrypted connections keyed by owner, workspace, and remote user.
5. Save the workspace returned by OAuth rather than trusting the requested workspace hint.
6. Add Connections status, workspace selection, local icons, and composer mentions.
7. Register a fixed read-tool allowlist with validated arguments.
8. Add explicit pagination, message permalinks, string timestamps, and partial-result markers.
9. Check content retention rules before adapting saved sources and R2 storage.
10. Add message writes and document tools as separate increments.

Keep Slack as an account connector. Telegram remains the first transport.
A Slack bot transport, Events API listener, and Socket Mode are separate projects.
Check each tool scope rather than granting all scopes from a sample manifest.
Keep current approvals, tool journals, private-account access, and no replay after uncertain writes.

## Acceptance and dependencies

Use the existing `mcp`, `httpx`, `cryptography`, and `jsonschema` dependencies.
A direct remote client needs no Bolt application, Node.js runtime, or local Slack MCP container.
The external setup still needs an eligible Slack app, HTTPS callbacks, and workspace authorization.
Check rate limits for the selected app and method rather than assuming one limit for every tool.

Test owner/workspace isolation, callback replay, token expiry or rotation, missing scopes, and disconnection.
Test private-search consent withdrawal, pagination, long threads, exact timestamps, and optional-service failure.
Test safe file handling before downloads and uncertain outcomes before uploads or message writes.
Check source recovery according to the permitted retention contract.

Live acceptance needs a disposable workspace or channel and an eligible app.
Check public search, authorized private search, complete thread reads, restart persistence, and disconnection.
Record denied access as denied access, not an empty successful search.
Keep mock results separate from live results in `docs/runtime/acceptance.md`.

## Open checks

- Is the initial deployment an internal app or a Marketplace app?
- Which workspaces permit the Theos integration?
- Which tool names and scopes does the actual endpoint expose?
- Which content can the runtime persist, and for how long?
- Which posting identity should later message tools use?

The branch remains independent of GitHub and GitLab implementation.
Coordinate shared credential migrations through `dev` before assigning migration numbers.
