# GitLab connector plan

Status: read-only adapter synchronized with current dev on 2026-10-28. Live account acceptance remains pending.
See [the setup guide](../gitlab-mcp.md) for the current supported scope.
Branch: `feature/gitlab-connector`. Updated base: `origin/dev` at `c8ce44b`.

## Tool evidence

The [official catalog](https://docs.gitlab.com/user/model_context_protocol/mcp_server_tools/) covers repositories, merge requests, work items, pipelines, and optional services.
The [inventory](gitlab-tools.json) separates representative current tools from documented legacy tools.
No GitLab connector appears in this Codex session.
No authenticated GitLab discovery or account request ran during this review.

| Area | Representative documented tools | Initial scope |
| --- | --- | --- |
| Discovery | `get_mcp_server_version`, `get_project`, `list_projects`, `list_groups` | Include when available |
| Repository reads | `get_repository_file`, `list_repository_tree`, `get_commit`, `list_commits`, `list_branches` | Include |
| Merge requests | `get_merge_request`, `list_merge_requests` | Include |
| Work items | `get_work_item`, `list_work_items`, `get_work_item_types` | Include when available |
| CI reads | `get_pipeline`, `list_pipelines`, `get_job`, `get_artifact_file` | Include metadata and bounded logs |
| Search | `search`, `search_labels`, `semantic_search` | Basic search first |
| Collaboration writes | `save_note`, `save_work_item`, `save_merge_request`, `save_merge_request_review` | Later increment |
| Repository and CI writes | `add_commit`, `add_branch`, `accept_merge_request`, `save_pipeline` | Deferred |
| Optional services | Wikis, vulnerabilities, Duo sessions | Deferred |

The catalog includes GitLab 19.5 changes and unlisted compatibility tools.
It does not establish availability on the target instance.
For example, newer schemas consolidate merge-request reads into facets of `get_merge_request`.
Older tools such as `get_merge_request_diffs` can remain callable after disappearing from discovery.
Do not count aliases or unlisted tools as guaranteed current capabilities.

## Complexity

These ratings are engineering estimates, not measured durations.

| Work | Complexity | Reason |
| --- | --- | --- |
| One modern instance, read tools | Medium-high | Schema versions, facets, and mixed pagination |
| Multiple self-managed instances | High | Separate origins, clients, versions, certificates, and settings |
| Authorization | High | MCP enablement and a distinct scope from ordinary REST access |
| Search | High | Instance configuration, indexing, and license-dependent features |
| Writes | High | Branch state, work-item types, notes, and CI effects |

The [server guide](https://docs.gitlab.com/user/model_context_protocol/mcp_server/) documents `https://<instance>/api/v4/mcp`.
Its current authentication contract accepts OAuth with the `mcp` scope.
The guide also documents eligible fine-grained personal tokens.
Legacy personal, project, and group tokens cannot substitute for the required MCP access.
Use per-instance OAuth registration and check server enablement before implementation.

Prefer official MCP when the target instance meets the required contract.
For older instances, evaluate a separate REST adapter with `read_api`.
The [REST OAuth guide](https://docs.gitlab.com/api/oauth2/) describes PKCE and rotating refresh tokens.
REST credentials and MCP credentials have different requirements.
Do not automatically broaden scopes or switch adapters after a failed call.

## Implemented scope

The deployment selects one GitLab instance. Each private owner authorizes a separate account grant.
`services/gitlab/` configures endpoints, toolsets, and the reviewed read allowlist.
The shared account adapter owns PKCE, encrypted credentials, refresh, cancellation, discovery, and schema validation.
Next.js Connections, onboarding, mentions, callbacks, and native Telegram controls use the current account paths.
Large reads use temporary result files. Journals retain tool outcomes and returned result pointers.
The generic harness and removed static frontend remain unchanged.
Issue, note, and merge-request writes require a separate increment.

Use configured instance origins and prevent credential forwarding through cross-origin redirects.
Handle project IDs separately from encoded project paths.
Preserve GitLab notes as content, including quick-action syntax, without treating them as Theos instructions.
Keep current approvals, account access, tool journals, and uncertain outcomes.
Do not delegate write access to research agents.

## Acceptance and dependencies

Use the existing `mcp`, `httpx`, `cryptography`, and `jsonschema` dependencies.
Direct HTTP avoids a Node.js `mcp-remote` proxy.
Keep GitLab protocols under `services/gitlab/` and client lifecycle in the application runtime.

Test owner and instance isolation, callback replay, token rotation, refresh/disconnect races, pagination, and schema differences.
Test missing MCP settings, unsupported scopes, partial facets, unavailable search, and optional-service failure.
Check result-file handling and preserve partial reads without claiming complete results.
Test permission removal and unknown write outcomes before enabling write tools.

Live acceptance needs a configured instance, an OAuth app, and a disposable project.
Check a complete merge request, a failed job log, restart persistence, and disconnection.
Record the exact server version and discovered schema evidence.
Keep mock results separate from live results in `docs/runtime/acceptance.md`.

## Open checks

- The operator selected GitLab.com. Its authenticated server version remains to be recorded.
- Does the operator permit MCP for that group or instance?
- Which read facets and pagination formats does the endpoint expose?
- Is basic search sufficient without semantic search or Duo?
- Is an older-instance REST adapter part of the first release?

The branch includes GitHub and Slack through dev and reuses their shared account adapter.
The GitLab connector adds no credential migration or provider SDK.
