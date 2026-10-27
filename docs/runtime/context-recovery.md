# Context compaction and task workspaces

The harness keeps the complete transcript and builds a smaller view for each model request.
Compaction changes only that view. The saved messages remain available through history tools.

## Rolling summary algorithm

1. Build a request from the stable instructions, current summary, recent messages, tools, and output setting.
2. Estimate the complete request, including tool schemas and images.
   Compact at the configured trigger ratio or when input plus output does not fit.
   The default trigger ratio is 50%.
3. Keep the configured fraction of recent messages as the raw tail.
   The default tail ratio is 2.5% of the context window.
   Keep a new unanswered user message verbatim.
   Keep each tool call with its results, or summarize the completed batch as a whole.
   Unfinished tool batches remain verbatim during normal compaction and overflow recovery.
4. Summarize earlier conversation history with the initial or update prompt.
   Supply the existing summary and only newly covered messages.
   Use the active model by default, or `AGENT_COMPACTION_MODEL` when set.
   Summary calls have no tools and cap output at the tail ratio of the summary model's context.
5. When the boundary splits a turn, summarize its original request and earlier progress in a separate call.
   Combine the history summary and split-turn summary into one checkpoint.
   Reuse the existing history summary when no new earlier history needs a summary call.
   If the original request already belongs to the checkpoint, update that checkpoint with new progress.
6. If one old message exceeds the configured trigger budget, give the summary its history index and tool identifiers.
   Keep its full content in the transcript for exact recovery through history tools.
   Include the original user request in full when building a split-turn summary.
7. Rebuild the request as system instructions, the combined checkpoint, and the retained messages.
   Do not insert a covered user request after the checkpoint.
   If it still does not fit, ask the model for shorter summaries in three tiers.
   Save the new summary and its transcript boundary only after the complete request fits.
   Both summary calls must succeed before a split-turn checkpoint can replace the previous view.
   The callback also saves the working session checkpoint.
8. If the provider rejects a request, leave the failed attempt out of active history.
   Summarize completed progress and retry with a smaller request.
   Keep new unanswered user messages and unfinished tool batches verbatim.
   A retry never repeats a completed tool call.

The summary is labeled as fallible context, not an instruction or proof of action.
The model can search and read exact saved messages with `history_search` and `history_read`.
If safe compaction cannot make a request fit, the runtime reports a context failure.
It does not remove the current task or claim that omitted evidence was reviewed.

The code lives in `src/harness/compaction.py` and `src/harness/context_size.py`.
The runtime supplies the summary model, ratios, model options, and checkpoint callback in `src/theos/runtime/context.py`.

## Summary prompts

The harness owns shared grounding rules and separate initial, update, and split-turn prompts.
Their production templates live under `src/harness/prompts/compaction/` as ordinary Markdown Jinja files.
Theos can override individual prompts through `CompactionConfig`. Missing overrides retain harness defaults.
See [prompt templates](prompts.md) for the override filenames and rendering rules.
Initial and update prompts use the same Markdown sections: Goal, Constraints & Preferences, Progress, Key Decisions, Next Steps, and Critical Context.
The update prompt preserves relevant earlier facts and applies new corrections, confirmed progress, and resolved blockers.
It keeps uncertain actions separate from confirmed completion.

The split-turn prompt has its own summary call and includes the original user request.
It uses Original Request, Progress So Far, and Context Needed to Continue sections.
The combined checkpoint places the split-turn summary after the earlier history summary.
Retained messages follow the checkpoint in their original order.
The covered original request appears inside the checkpoint and is not repeated as a fresh user message.

The checkpoint uses the provider's user-message role and identifies its contents as fallible conversation history.
It instructs the model to continue from saved progress without repeating completed work.
The full transcript remains unchanged.

`CompactionConfig.additional_instructions` adds optional focus to each summary request.
Shortening passes request a paragraph, three sentences, and then one sentence.
They omit the structured format so the heading requirements cannot conflict with the shorter output.
Each history, split-turn, or shortening call uses the shared summary allowance and records its own usage.
If either part fails, keep the previous view when it still fits. Otherwise, report a context failure.

New checkpoints use memory schema version 5.
Version 4 checkpoints recover their omitted request from saved history and include it inside the checkpoint.
They retain the old schema marker until a successful compaction saves the complete replacement.
Legacy saved working views remain readable until their next successful compaction.

## History and research scratchpad

The harness registers `history_read` and `history_search` as ordinary tools.
Both read the saved conversation text without rewriting its content.
`history_read` pages a message by index or tool call ID.
`history_search` returns matching message indexes for later reading.

Deep Research keeps its evidence in the conversation-owned `research_scratchpad` table.
Migration 013 renames the earlier evidence table without losing saved records.
Research services keep their existing read and save behavior.
Compaction neither summarizes nor changes scratchpad records.

## Provider sizing

The runtime reads model capacity from its catalog and refreshes OpenRouter metadata once per hour.
An operator can set `AGENT_CONTEXT_TOKENS` to choose a smaller window.
Unknown models use a logged 24,000-token context fallback.
The runtime includes the requested output limit when it checks each request.
It does not lower that limit to make an oversized request fit.

The harness uses a conservative UTF-8 estimate when provider usage does not describe the current request.
The estimate includes tool schemas, message framing, and a safe image allowance.
It does not require a tokenizer package.

## Provider result detail

Gmail search returns selected headers and short snippets, not full messages or MIME payloads.
`gmail_get_message` accepts a message ID and body range, and lists attachment metadata without attachment contents.
The model can download one selected attachment by message ID and attachment ID.
Health returns compact daily metrics by default. Date-range and metric arguments fetch specific detail when needed.
These details come from Gmail or Health on demand; Theos does not archive full provider responses in a generic source store.

| Tool | Purpose |
| --- | --- |
| `history_read` | Read exact saved message text by index or tool call ID |
| `history_search` | Search saved message text and return indexes for reading |

History tools can read only the current agent's transcript.

Immutable session objects live under `theos/checkpoints/<owner hash>/<session>/` in R2.
The local private spool and SQLite `context_objects` table track each transfer.
An R2 outage leaves the local object pending for a background retry.
The remote checkpoint pointer advances only after the snapshot and its referenced objects upload.

Checkpoints include the full transcript, summary boundary, model state, tool states, and workspace manifest.
Delegates also save their task and model state as checkpoint objects.
Restoration checks ownership and content hashes.
An interrupted action remains uncertain after restore, so the runtime never reruns it automatically.
Ordinary restarts use SQLite. `Checkpoints.restore` supports controlled restoration into an owned, empty session.
R2 does not contain provider reasoning that the provider never returned.

## Normal sandbox use

The model can choose the sandbox for calculations, data processing, scripts, file inspection, or document creation.
The user does not need to ask for a sandbox.
Commands and Python execution start in `/workspace`.
The wrapper saves changed files, including nested files, after each operation.
Each changed file gets an immutable R2 version and a manifest entry.
A replacement sandbox restores missing files.
Reconnection keeps newer files already present in a live sandbox.
Files outside `/workspace` are outside this checkpoint contract.
Existing approval checks still apply to execution and external actions.

## Call budgets and failures

Theos uses `Runtime(enforce_budgets=False)` by default.
The configuration keeps call limits for bounded callers.
Provider context and output limits, tool timeouts, concurrency, ownership, and approvals remain active.
See [optional call budgets](call-budgets.md) for bounded mode.

An unavailable provider or an irreducible request can still stop a turn.
When that happens, the runtime preserves the transcript and reports failure.
A failure message never counts as a useful answer in replay tests.

## Visible activity and approval reviews

Compaction emits started, progress, completed, or failed events with token estimates.
Events do not include private summary text.
Browser chat shows a live context indicator.
Telegram edits one status message for each compaction.
Both clear active indicators when the turn stops.
Browser disconnects also clear the local indicator.

Telegram shows a tool icon, readable action name, and status for each call.
Protected actions show requested or waiting for approval before execution.
Approval reviews group cart items and show short labels before exact request details.
Repeated aliases share a field.
The original approval snapshot still controls execution.
Long Telegram reviews retain all details through message splits or an attached review file.
For `zepto_update_cart`, cart price and maximum retail price use paise.
The review shows `3900` as `₹39.00` and retains `3900` in exact request details.
The display conversion never changes approved arguments.

## Validation

`scripts/replay_context_failure.py` replays a saved session with a live model and local history tools.
It checks expected facts and source reads without using production connectors or Telegram.
Use task-specific expectations to check answer completeness.
See [acceptance checks](acceptance.md) for results and limits.

## Local checkpoint latency and remote replication

SQLite state and fsynced local objects remain durable before model requests and tool execution.
Checkpoint creation does not wait for R2.
One worker scans bounded batches from the SQLite transfer journal and reuses its storage connection.
Failed transfers remain pending.
Restarted workers retry storage operations without repeating assistant tools.

The worker publishes a remote recovery pointer only after it uploads the snapshot and all conversation sources.
Remote recovery can lag the current local transcript during an outage or transfer backlog.
Local recovery continues from SQLite and the checkpoint directory.
Back up both stores.
Do not treat an outstanding remote transfer as an external action failure.

Independent Gmail reads can overlap within bounded tool batches.
Each call keeps its ownership check, journal entry, result, and original order.
Writes and approved sends remain sequential.
An unfinished action remains uncertain after interruption.
See [the recovery diagram](../architecture/theos-runtime-recovery.excalidraw) and [latency diagnostics](../base-infra/observability.md#diagnose-turn-latency-and-provider-failures).

Remote restore pauses tool access for that conversation until operator reconciliation.
A snapshot can omit calls and actions that occurred after its upload.
Captured unanswered calls become saved results or uncertain outcomes before the runtime resumes.
The owner-bound review record survives compaction and later checkpoints.
After checking external effects, operator recovery code calls `checkpoints.confirm_restore_review(owner, session)`.
This method cannot run as an agent tool and rejects confirmation during a running turn.
Uncertain call records remain intact after review.
The runtime never executes them automatically.

## Runtime checkpoint retention

Theos owns checkpoint retention in `services/files/retention.py`. The generic harness has no storage or garbage-collection policy.
The default policy keeps three recent recovery checkpoints per session, the current workspace, response attachments, and local and published remote pointers.
Every retained checkpoint protects its declared file sources. New snapshots declare current workspace and attachment versions without accumulating older workspace objects.
Older snapshot formats remain readable and keep their original source references while retained.

The existing background checkpoint worker runs collection, including when R2 is disabled.
An hourly scan retires eligible objects after one hour since their last storage or reuse.
Each pass marks at most 20 objects. Backlogs continue through further bounded passes.
Active sessions and sessions awaiting remote-recovery review defer collection. Missing or corrupt retained snapshots also defer collection for their session.
The collector preserves research evidence, browser profiles, uploaded-file catalog entries, and conversation history.

SQLite migration 015 records pending object deletions before removal.
The worker handles R2 partial failures and retries with backoff. Retirement does not repeat assistant commands.
A recreated content-addressed object stays local while its earlier remote deletion finishes. Its replacement upload follows that deletion.
Recovery pointers advance only after their declared dependencies exist remotely.
The collector protects the older published snapshot while newer local state awaits replication.
Pointer publication records its intent before the remote write. Lost responses retain every possibly published snapshot until a later publication is confirmed.
Remote restoration registers the fetched snapshot as a recovery root, including on a fresh database.

Configure `AGENT_STORAGE__CHECKPOINT_KEEP`, `AGENT_STORAGE__GC_INTERVAL_SECONDS`, and `AGENT_STORAGE__GC_GRACE_SECONDS` in the deployment environment.
