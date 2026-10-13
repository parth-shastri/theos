# Call budgets

Theos disables these allocations and research deadlines in its default harness.
The settings, diagrams, and rules below describe the retained bounded mode only.
Read [context recovery and active limits](context-recovery.md) for the default behavior.

Each user message starts one shared call budget. Normal questions and explicit deep research use the same budget rules.
A delegate does not receive an extra pool of calls.
Open the [Excalidraw overview](call-budgets.excalidraw) for a 50-call example using the default ratios.
The diagram shows the allocation and the purpose of each allowance.
The descriptions, formulas, and checks are below.

![Budget allocation for a 50-call turn](call-budgets.png)

## Derive the allocation once per turn

`AGENT_MAX_MODEL_CALLS` is the total. Explicit summary and delegate counts take precedence.
When a count is omitted, multiply the total by its configured ratio and round up:

- Summary calls: `ceil(total × AGENT_COMPACTION_CALL_RATIO)`. The default ratio is one-sixth.
- Delegate research and handoff ceiling: `ceil(total × AGENT_DELEGATE_CALL_RATIO)`. The default ratio is one-third.
- Parent final response: one held call, following the single-response rule.
- Shared research calls: `total − summary calls − 1`.

Summary allocation is capped at `max(total − 2, 0)` to retain research capacity on small totals.
The delegate ceiling is capped at the shared research allowance. These caps also apply to explicit counts.
Resolve these values once when the turn starts. The runtime and traces use the same resolved values.

| Total | Shared research | Shared summaries | Parent final response | Each delegate's research and handoff ceiling |
| --- | --- | --- | --- | --- |
| 30 | 24 | 5 | 1 | 10 |
| 50 | 40 | 9 | 1 | 17 |
| 100 | 82 | 17 | 1 | 34 |

The delegate ceiling does not create more calls. Parent and delegate research share the same research allowance.
Each delegate holds its handoff before any sibling starts. A delegate without a handoff slot does not start research.
Delegate summaries use the separate shared summary allowance. They count toward the total, outside the delegate's research and handoff ceiling.
A normal parent answer consumes a research call. The held parent response is for limits or interrupted research.

Summary holds come from the existing summary allowance. They do not increase the total.
At 30 calls, three active delegates hold four summaries with the parent, leaving one for ordinary summaries.
At 50 calls, the same holds leave five for ordinary summaries.
Completed delegates release unused holds. Later research summaries can use those released calls.
The parent's summary hold stays available until its final response or the end of the turn.
A final response uses its held summary first, then any unheld summary calls still available.

## Before every request

The bounded mode checks its call allowance before building the request.
Both modes then use the same [context and workspace algorithm](context-recovery.md).
The context check prunes old tool results and, when needed, summarizes the middle once.
It does not split complete evidence into a chain of summary calls.

## When research stops

The final-response path uses the same compression policy before calling the model.


The held summary is a protected opportunity, not a promise that any amount of evidence will fit.
A distinct auxiliary model can require one main-model retry. Large original requirements can still exceed the model window.
If summaries fail or cannot fit, the application retains the evidence and returns a clear failure.
It does not retry the final response or cut the text to force a fit.
Provider failures return a clear explanation without another research attempt.
Explicit cancellation interrupts the turn instead of starting a final response.

## Configuration and accounting

| Setting | Default | Where the harness enforces it |
| --- | --- | --- |
| `AGENT_MAX_MODEL_CALLS` | `30` | Shared ceiling charged by every research, summary, title, and final response call |
| `AGENT_MAX_COMPACTION_CALLS` | Unset; derived from total | Optional explicit shared summary count. Zero disables summaries |
| `AGENT_COMPACTION_CALL_RATIO` | `1/6` | Summary fraction when the explicit count is absent, from 0 to 1 |
| `AGENT_DELEGATE_MAX_MODEL_CALLS` | Unset; derived from total | Optional explicit research and handoff ceiling per delegate |
| `AGENT_DELEGATE_CALL_RATIO` | `1/3` | Delegate fraction when the explicit count is absent, greater than 0 and at most 1 |
| Parent final response | `1` | Held automatically within the total. Legacy `AGENT_MAX_RECOVERY_CALLS` does not add attempts |
| `AGENT_TURN_TIMEOUT` | `300` seconds | Before new main-agent model calls and tools |
| Delegate research deadline | `85` seconds | Before new delegate model calls and tools, also bounded by the parent's research deadline |
| Ordinary tool timeout | `90` seconds | Tool execution. Delegation groups permit active final responses to finish |
| `AGENT_COMPACTION_TRIGGER_RATIO` | `0.5` | Upstream floors and scaled summary allocations apply |
| Conversation `max_output_tokens` | 8,192 by default | Main generation parameter. Auxiliary summaries use a prompt target without a hard output cap |

Explicit counts override their ratios independently. Remove old explicit counts from `.env` to enable derivation.
For example, keeping `AGENT_DELEGATE_MAX_MODEL_CALLS=10` keeps that ceiling at ten when the total becomes 50.
The example environment file leaves both count overrides commented out.
After changing environment values, recreate the container so the process reads them.

For smaller totals, summary allocation is `min(requested summaries, max(total - 2, 0))`.
The parent still holds one final response. Research receives the remaining calls.
A total of one therefore permits only the final response.
Unused summary calls do not become research calls.

Tools do not consume model-call slots themselves. The model call that selects a tool does.
A delegated tool can start child model calls, which consume the same shared allowance.
Title generation consumes a research slot. It can be skipped when that allowance is exhausted.
Provider SDK connection retries remain inside a charged model call. This ceiling counts harness model calls, not individual HTTP attempts.
Memory-service calls, search requests, and account APIs are separate service requests.

For agents, only the provider's max output tokens parameter enforces generation length.
The application does not cut or reject returned answers by size.
When no output value is known, one shared 8,192-token estimate reserves context space without setting a generation limit.
Tracing has separate capture limits that do not change answers.

Code: [allocation](../../src/theos/runtime/budgets.py), [delegates](../../src/theos/runtime/tools.py),
[request checks](../../src/harness/loop.py), [summary calls](../../src/harness/compaction.py),
and [final responses](../../src/theos/runtime/recovery.py).
