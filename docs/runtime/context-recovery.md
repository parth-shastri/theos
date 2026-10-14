# Context compression and task workspaces

Theos uses one compression policy for parent agents, delegates, and final responses.
The policy protects the head and recent tail, prunes tool output first, and summarizes the middle with an auxiliary model.
The source revision and MIT license are in `src/harness/compression_provenance.json` and `src/harness/compression_LICENSE`.
Theos supplies message, provider, storage, and asynchronous execution adapters around that policy.

Open the [editable context and workspace diagram](context-workspace.excalidraw).

## End-to-end algorithm

1. Save each user message and completed tool result in the conversation journal.
   Preserve the original transcript independently of the model's working context.
2. For Gmail and Health read tools, save the complete response before returning a readable page.
   Return a source ID, storage status, and continuation offset with that page.
3. Build the next model request from the working context and new journal messages.
   Attach current instructions, tool schemas, research references, and the requested output limit.
4. Save a checkpoint before the model call.
   Use provider input usage when the request prefix and tool schemas match the saved usage anchor.
   Otherwise, use the upstream UTF-8-aware rough estimate, including schemas and image costs.
5. Compare the complete input against the compression threshold and available input space.
   If neither limit is reached, call the model.
6. When compression is needed, prune duplicate and old tool results first.
   Protect a recent pending tool round when it fits its allocation.
   Preserve tool-call arguments and keep complete call/result groups.
7. If pruning supplies enough space, save the working context and continue.
   Otherwise, select the protected head and a tail by token cost.
   The first compression protects the system prefix and three additional messages.
   Later compressions reduce that additional head protection because the summary carries earlier context.
8. Summarize the middle with the previous summary, exact identifiers, user quotations, and saved research references.
   Sample large summary inputs across the middle within 160,000 characters.
   Fit the sample to the auxiliary model's capacity before its single summary request.
   Use the scaled summary target in the prompt, without a hard summary output cap.
9. Reject empty, refused, or truncated summaries.
   A distinct auxiliary model gets one retry through the main model.
   These failures discard the rejected output and apply a cooldown to later summary calls.
   Repeated timeouts or sustained overload can produce a deterministic continuity summary.
10. Check the complete candidate against the window after reserving output space.
    If necessary, cut tool results, optional replay data, summary text, old complete exchanges, and optional tool documentation.
    Check again after each cut until the request fits. This loop has no fixed retry count.
    If a summary fails, apply the same cuts to the remaining request.
    Preserve current instructions, active user messages, pending tool batches, and tool validation contracts.
11. Save the fitted working context, full reference index, transcript boundary, and recovery state together.
    Publish the candidate only after its checkpoint succeeds. A failed transaction restores previous active memory.
    Continue the task with the same tool names and saved sources.
12. Save another checkpoint after the model response, after tools, and when the turn ends.
    If the provider rejects context, reduce the rejected request before another attempt. There is no fixed retry count.
    A retry must reduce estimated tokens, or serialized bytes when the token estimate stays equal.
    Recovery never repeats a completed tool or retries an identical request.
    Only a provider-reported limit can lower the saved model capacity. Recovery does not guess a smaller window.

The check happens immediately before each main model call, after application hooks finish building the request.
Compaction does not run as an independent research agent with its own tool loop.
The summary model receives a bounded request without tools.

## Text summary structure

The summary model returns Markdown text with the pinned policy's section headings.
The application does not request JSON generation or parse summary prose as JSON.
Fresh summaries and later updates use the same template:

```text
## Historical Task Snapshot
## Goal
## Constraints & Preferences
## Completed Actions
## Active State
## Blocked
## Key Decisions
## Errors & Fixes
## Resolved Questions
## Relevant Files
## Critical Context
## Detailed Session Log (oldest first)
```

Lean mode includes the detailed session log. The prompt requests Pruned Skills only when relevant markers exist.
Code supplies Anchor Index, User Messages, and Context Recovery sections from original data.
Code replaces model-written versions of those sections before publication.

The reference index includes exact tool identifiers, original message indices, and saved research IDs.
It also identifies unknown tool outcomes. A summary cannot establish that an uncertain action succeeded.
The model request receives a bounded reference index. Saved memory retains the full index in `state.references`.
SQLite and later R2 checkpoints retain this index with the working context and full transcript.
Research IDs come from owned application records. The model does not need to repeat every ID for acceptance.

The runtime saves parent history and memory before the next answer request.
A failed SQLite transaction restores the previous active memory. Child summaries never replace the parent session.
Existing history tools recover omitted details by original message index or tool call ID.

`AGENT_COMPACTION_TAIL_MODE=lean` retains the current recovery policy's default token tail.
Set it to `current` for a larger recent tail without the detailed session log.
`AGENT_COMPACTION_MIN_TAIL_USER_MESSAGES` defaults to one and accepts values from one through twenty.
Both modes preserve complete tool exchanges and the active request.
Further cuts can replace verbose results with retrieval notes or remove old complete exchanges from working context.
A short handoff records missing evidence and uncertain actions when a summary cannot supply enough space.
The full transcript and reference index remain in storage, even if their request copy needs further cuts.
A request without retrieval tools must state missing evidence rather than invent omitted details.

## Scaled allocations

| Allocation | Rule |
| --- | --- |
| Effective input space | Context window minus requested output |
| Trigger fraction | Default 0.5, with a 0.75 floor for windows below 512,000 tokens |
| Threshold floor | 64,000 tokens, bounded by 85 percent of effective input when the floor binds |
| Recent tail | 2.5 percent of the window, normally 10,000–25,000 tokens, capped at 20 percent of the window |
| Summary target | Nominally 20 percent of middle tokens, with the pinned minimum and ceiling, further reduced to fit retained input and output |
| Summary input | Distributed record sample, at most 160,000 characters, further reduced for auxiliary capacity |
| Summary timeout | 120 seconds per attempt |
| Fit cuts and provider overflow | No fixed retry count. Every recovery request must be smaller |

At the Pi's 100,000-token window and 8,192-token output reservation, the default threshold is 68,856 input tokens.
The tail allocation is 10,000 tokens. The nominal summary ceiling is 5,000 tokens.
The summary prompt includes the structured continuation log within the available request space.
The model can exceed this target. The fit loop checks its actual returned text and cuts further when needed.
These are context allocations, not fixed numbers of research calls.

`AGENT_COMPACTION_MODEL` selects the auxiliary model. OpenAI and OpenRouter default to `gpt-6-luna`.
Other providers use the conversation model unless an auxiliary model is configured.
Anthropic requires an output maximum. Its adapter uses available capacity, bounded by the model limit, rather than the summary target.
`AGENT_COMPACTION_CONTEXT_TOKENS` can set its capacity explicitly.
`AGENT_COMPACTION_TRIGGER_RATIO` defaults to 0.5.
The upstream policy applies its small-window floor to that configured fraction.

## Connector sources and R2

The wrappers leave Gmail, Health, and MCP implementations unchanged.
They return at most 12,000 characters initially. Gmail text views decode MIME bodies and identify unread attachments.
They retain identifiers, units, dates, and provider pagination tokens.

| Tool | Purpose |
| --- | --- |
| `source_read` | Read a saved connector result in pages, in raw or readable form |
| `source_to_workspace` | Copy the complete saved result into `/workspace` without passing it through model context |
| `history_read` | Recover original transcript content by message index or tool call ID |
| `history_search` | Search or list original transcript sources, excluding retrieval copies |

Source IDs require the same authenticated owner and conversation.
History tools operate only on the current agent's history.

Immutable compressed objects live under `theos/checkpoints/<owner hash>/<session>/` in R2.
The local private spool and SQLite `context_objects` table track each transfer.
An R2 outage leaves the local object pending. The background worker retries the transfer without repeating the connector call.
The latest remote checkpoint pointer advances only after all referenced objects are saved.

Checkpoints include the full journal, working context, model state, tool execution states, and workspace manifest.
Delegates also save their own task and model state as checkpoint objects.
Restoration checks ownership and content hashes.
An interrupted action remains uncertain after restore. Restoration does not rerun it.
Ordinary process restarts use SQLite. `Checkpoints.restore` supports controlled restoration into an owned, empty, inactive session.
R2 does not contain provider-internal reasoning state that the provider never returned.

## Normal sandbox use

The model can choose the sandbox when a task needs calculations, data processing, scripts, file inspection, or document creation.
The user does not need to ask for a sandbox.
Commands and Python execution start in `/workspace`. Relative file paths resolve there.
The wrapper saves changed files, including nested files, after each operation, even when a command fails.
Each changed file gets an immutable version in R2 and a manifest entry.
A replacement sandbox restores missing files. Reconnection preserves newer files already present in a live sandbox.
Files outside `/workspace` are outside this checkpoint contract.
Existing approval checks still apply to execution and external actions.

## Call budgets and remaining limits

Theos uses `Runtime(enforce_budgets=False)`.
The configuration retains total, research, compaction, recovery, and delegate call settings for bounded callers.
The default harness counts calls without enforcing those allocations or research deadlines.
There is no fixed three-batch retrieval cutoff.

Provider context and output limits remain active, as do summary timeouts, tool timeouts, upload sizes, concurrency, ownership, and approvals.
Title generation retains its separate attempt policy.
There is no configured dollar-spend or cumulative token-spend ceiling.
See [optional call budgets](call-budgets.md) for bounded mode.

Summary failure and oversized summary output do not stop a task when safe cuts can make the request fit.
Compression cannot guarantee an answer for an unavailable provider or an irreducible request.
If a provider rejects the smallest safe request, the runtime preserves the evidence and reports failure.
A fixed failure message does not count as a useful answer in replay tests.

## Visible activity and approval reviews

Compaction emits started, progress, completed, and failed events with a separate identifier for each compression.
Events include token estimates and scope, without private summary prose.
Browser chat shows a live context indicator. Telegram edits one status message for each compression.
Both clear active indicators when the turn stops. Browser disconnects also clear the local indicator.
Telegram shows a tool icon, readable action name, and status for each call.
Protected actions show requested or waiting for approval before execution.

Approval reviews group cart items and show short labels before exact request details.
Repeated aliases share a field. The original approval snapshot still controls execution.
Browser disclosures and Telegram expandable quotes retain technical identifiers and raw price values.
Long Telegram reviews retain all details through message splits or an attached review file.
For `zepto_update_cart`, cart price and maximum retail price use paise.
The review shows `3900` as `₹39.00` and retains `3900` in exact request details.
The display conversion never changes approved arguments. Other tool prices retain their supplied units.

## Validation

`scripts/replay_context_failure.py` replays a private saved session with a live model and local history tools.
It preserves the original transcript, checks expected facts and source reads, and does not access production connectors or Telegram.
Use task-specific expectations to check answer completeness.
See [acceptance checks](acceptance.md) for results and limitations.

## Local checkpoint latency and remote replication

SQLite state and fsynced local objects remain durable before model requests and tool execution.
Checkpoint creation does not wait for R2.
One worker scans bounded batches from the SQLite transfer journal and reuses its storage connection.
Failed transfers remain pending. Restarted workers retry storage operations without repeating assistant tools.
A failed object cannot prevent another conversation from receiving transfer attempts indefinitely.

The worker publishes a remote recovery pointer only after its snapshot and all conversation sources are uploaded.
Remote recovery can therefore lag the current local transcript during an outage or transfer backlog.
Local recovery continues from SQLite and the checkpoint directory.
Back up both stores. Do not treat an outstanding remote transfer as an external action failure.

Independent Gmail reads can overlap within the existing bounded tool batches.
Each call retains its ownership check, journal entry, result, and original result order.
Writes and approved sends remain sequential. An unfinished action remains uncertain after interruption.
See [the recovery diagram](../architecture/theos-runtime-recovery.excalidraw) and [latency diagnostics](../base-infra/observability.md#diagnose-turn-latency-and-provider-failures).
