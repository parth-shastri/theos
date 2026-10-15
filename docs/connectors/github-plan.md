# GitHub connector plan

Status: read-only adapter implemented on 2026-10-15. Live account acceptance remains pending.
See [the setup guide](../github-mcp.md) for the current supported scope.
Branch: `feature/github-connector`. Base: `origin/dev` at `8a4360f`.

## Tool evidence

The [official server](https://github.com/github/github-mcp-server) groups tools by repository, issue, pull request, Actions, and other services.
The [remote guide](https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md) supports selected toolsets and read-only mode.
The accompanying [inventory](github-tools.json) records official tool identifiers and the separate Codex session snapshot.
The session exposes 89 GitHub tools. This does not prove access through a Theos credential.

| Area | Representative official tools | Initial scope |
| --- | --- | --- |
| Identity | `get_me` | Include |
| Repository discovery | `search_repositories`, `list_branches` | Include |
| Files and commits | `get_file_contents`, `get_repository_tree`, `get_commit`, `list_commits` | Include |
| Issues | `issue_read`, `list_issues`, `search_issues` | Include |
| Pull requests | `pull_request_read`, `list_pull_requests`, `search_pull_requests` | Include |
| Actions | `actions_list`, `actions_get`, `get_job_logs` | Include read methods |
| Collaboration writes | `issue_write`, `add_issue_comment`, `create_pull_request`, `pull_request_review_write` | Later increment |
| Repository writes | `push_files`, `create_or_update_file`, `merge_pull_request`, `delete_repository` | Deferred |
| Additional services | Projects, notifications, discussions, security, Copilot | Deferred |

Official identifiers differ from the Codex connector identifiers.
Treat tool names, method parameters, schemas, and negotiated protocol versions as a versioned contract.
Check code-search support with the actual credential before promising it.

## Complexity

These ratings are engineering estimates, not measured durations.

| Work | Complexity | Reason |
| --- | --- | --- |
| Read-only MCP adapter | Medium | Existing MCP libraries help, but sessions and schemas need explicit contracts |
| Account authorization | Medium-high | User identity, installation access, expiry, refresh, and organization policies |
| Content handling | Medium | Large patches, logs, binary resources, pagination, and source links |
| Write tools | High | Branch state, review semantics, external effects, and uncertain outcomes |
| Full catalog | High | Many unrelated permissions and workflows |

Prefer the official remote MCP server after an authenticated compatibility probe.
Use a GitHub App with owner-bound user authorization where supported.
Confirm token compatibility with the remote server rather than assuming every GitHub token works.
The [user-token guide](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app) describes state, PKCE, and token exchange.
Keep a direct REST adapter as an explicit alternative if MCP cannot satisfy the required access.
Do not silently switch authentication or protocols during a failed action.

## Delivery steps

1. Probe authorization, protocol negotiation, complete `tools/list` pagination, schemas, and one repository read.
2. Save a sanitized schema snapshot and classify each selected method as a read or write.
3. Add `services/github/` with small authentication, client, and tool modules.
4. Add owner-bound connection state, cancellation, token refresh, and disconnection.
5. Add an additive credential migration if multiple GitHub accounts need separate records.
6. Add Connections status, account selection, local icons, and composer mentions.
7. Register a fixed read-tool allowlist with validated arguments and `github_` names.
8. Preserve complete fetched responses through the existing source and checkpoint services.
9. Add collaboration writes as a separate increment after read acceptance.

Keep authorization decisions in Theos.
Remote annotations alone cannot classify a tool as safe for parallel execution.
Keep the current approval policy and durable unknown-outcome handling.
Do not add provider credentials to model context, logs, or sandboxes.

## Acceptance and dependencies

Use the existing `mcp`, `httpx`, `cryptography`, and `jsonschema` dependencies.
The remote path needs no local Node.js runtime or GitHub server container.
Keep client lifecycle under the application runtime and provider behavior under `services/github/`.
Do not change generic harness behavior.

Test owner isolation, callback replay, expiry, refresh/disconnect races, schema changes, pagination, and optional-service failure.
Test source retrieval after compaction, ordered writes, and no replay after an uncertain action.
Check registration through browser, private Telegram, and connected terminal access.
Keep group chats and standalone terminal accounts outside private account access.

Live acceptance needs a disposable repository and an operator-configured app.
Check repository access removal, a complete pull request summary, restart persistence, and disconnection.
Record mock results separately from live results in `docs/runtime/acceptance.md`.

## Open checks

- Which organization policies and repositories must the first account support?
- Does the selected user token work with the remote endpoint and required tools?
- Which schemas and protocol versions does the deployed MCP library negotiate?
- Does repository-scoped code search work with that credential?
- Should additional accounts use a separate connection table?

The branches share no implementation dependency.
Extract only small common credential helpers after the first adapter proves their need.
Assign migration numbers when implementation branches integrate into `dev`.
