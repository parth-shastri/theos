# Architecture

The uploaded Agent Harness framework defines the Theos architecture.
It connects working context, the model and tool loop, memory, consolidation, and the operations feedback loop.
The default provider is OpenAI Responses with `gpt-6-luna`.
The configured `AGENT_NAME` supplies the assistant identity.

## Complete framework

![Agent Harness framework](architecture/theos-framework.png)

This is the primary architecture view.
The [original framework](architecture/reference/Agent-Harness.excalidraw) preserves the uploaded design.
The [editable redraw](architecture/theos-framework.excalidraw) adds Theos labels and tool groups.
Each section below maps that design to current code and identifies incomplete paths.

### Working context and execution

The framework combines the user prompt, recent turns, system instructions, and user context into working memory.
The model receives that context and selects a response or tool calls.
Tool results return to the loop until an end condition stops execution.

The current runtime restores conversation history and saved context before each turn.
It adds application instructions and user preferences.
The harness builds model requests, runs tools, and compacts context when needed.
The context budget controls retained history rather than a fixed number of recent turns.
Model-call limits, timeouts, approvals, and completion conditions bound execution.

Source: [runtime engine](../src/theos/runtime/engine.py) and [owned harness](../src/harness/).

## Memory and consolidation

![Memory and consolidation framework](architecture/theos-memory.png)

The framework separates working memory from procedural, semantic, and episodic memory.
Each store supplies a different kind of context.
The consolidation path turns selected conversation material into durable facts after a configured number of chats.

| Framework component | Purpose | Current implementation |
| --- | --- | --- |
| Working memory | Context for the active model loop | Conversation history, instructions, preferences, and harness compaction |
| Procedural memory | Procedures and reusable instructions | Operator-installed `SKILL.md` files and bounded resource reads |
| Semantic memory | Durable facts and user information | Local preferences, explicit tools, and bounded automatic retrieval |
| Episodic memory | Dated events across conversations | Persistent conversations and personal records, without general episodic retrieval |
| Consolidation | Distill facts from consented user messages | Durable queue and Mem0 OSS inference |

Retrieval-augmented generation (RAG) supplies retrieved material to a model request.
The RAG paths in the framework express the intended connections between stored knowledge and working context.
The application currently exposes explicit memory and record tools.
It does not implement automatic retrieval across every memory category or an automatic `User.md` context source.

Consented consolidation runs after a configured message count or elapsed interval.
The current implementation delegates extraction and fact merging to the configured Mem0 service.
The diagram's separate extractor model remains a framework concept, not another local Theos model.
Context compaction summarizes an active conversation but does not create authoritative personal records or grant permissions.

Ordinary chat continues during optional memory outages.
Only opted-in users' new text from completed private turns enters automatic consolidation.
Groups, scheduled prompts, assistant output, and tool output are excluded.
Read the [memory guide](memory.md) for current tools, ownership checks, and service setup.

## Operations feedback loop

![Operations feedback loop](architecture/theos-operations.png)

Large language model operations (LLMOps) surround the harness with a feedback process.
The framework connects traces to evaluation and observation, then diagnosis, a release gate, and deployment of reviewed changes.
Failed evaluations return to diagnosis and another evaluation cycle.

| Framework stage | Current implementation | Remaining framework work |
| --- | --- | --- |
| Trace | Runtime events in SQLite and structured application logs | Complete session traces and remote exporters |
| Evaluate | Deterministic harness and application acceptance tests | Simulation and model-based scoring |
| Observe | Health endpoints, usage records, and the private dashboard | Broader production metrics and latency analysis |
| Diagnose | Operator inspection of logs, traces, jobs, and conversations | Automated feedback into evaluations |
| Gate | Repository acceptance workflow | Evaluation-based release gates |
| Release | Manual image build, deployment, and rollback procedures | Automated release feedback across prompts, tools, retrieval, and models |

The diagram includes Langfuse, LangSmith, and custom exporters as design options.
The application does not configure those integrations or a remote OpenTelemetry exporter.
A passing mock test does not establish live service success.
Read [observability](base-infra/observability.md), [operations](operations.md), and the [acceptance checklist](runtime/acceptance.md) for current behavior.

## Tool design

![Framework tool design](architecture/theos-tools.png)

Tools connect the model loop to application records and external services.
The design groups search, weather, memory, personal records, sandbox execution, files, speech, and account integrations.
The harness receives callable tools from the runtime.
Each service owns its validation, records, and external protocol.

This diagram preserves an earlier tool design.
Some names and delivery phases differ from the implementation.
The [tool catalog](tool-catalog.md) is the authority for current callable names, dependencies, and approval rules.
The runtime exposes tools according to configuration, authenticated identity, and transport.
A diagram label does not grant access to a tool.

## Current implementation

![Runtime and service boundaries](architecture/theos-services.png)

This runtime diagram maps framework responsibilities to the current code directories and running services.
The harness owns generic execution behavior.
The application runtime connects that harness to storage, approvals, transports, and service clients.
The scheduler handles reminders, agent tasks, consented memory consolidation, and account jobs.
The [code structure guide](code-structure.md) uses this diagram as its main navigation view.

| Framework responsibility | Code location |
| --- | --- |
| Working context and model/tool loop | `src/harness/`, `src/theos/runtime/engine.py` |
| Tool composition and permissions | `src/theos/runtime/tools.py`, `src/theos/runtime/approvals.py` |
| Procedural memory | `src/theos/services/skills/` |
| Explicit memory and personal records | `src/theos/services/`, `src/theos/storage/` |
| Traces and usage | `src/theos/runtime/events.py`, `src/theos/runtime/usage.py` |
| Application logs and operator views | `src/theos/operations/`, `src/theos/transports/browser/` |
| Transport input and delivery | `src/theos/transports/` |

### Application process

`python -m theos.server` starts the FastAPI application.
Its lifespan creates the database, runtime clients, scheduler, and optional Telegram poller.
One process owns each data directory.
A filesystem lock rejects another process that tries to use the same directory.

The runtime reserves one active turn per conversation.
A semaphore limits concurrent conversations.
Model calls share a per-turn budget with research delegates.
The runtime also limits turn duration and the model context.

### Request paths

Telegram identifies the sender before a command or model turn.
Private chats, groups, topics, and group senders have separate conversation identities.
The poller saves inbound updates and the next offset in one database transaction.
It then dispatches pending updates.

![Telegram and durable checkpoints](architecture/theos-telegram.png)

The sequence diagram explains checkpoint order.
The current transport stores inbound updates and reminder delivery state.
It does not implement a general durable outbox for every streamed reply.

Browser API requests use a bearer token from `AGENT_USERS`.
The server derives the owner from that token.
A caller cannot select another owner through the request body.
The browser receives turn events through an HTTP stream.

### Harness and services

The harness owns the model and tool loop, context handling, compaction, hooks, and provider adapters.
The runtime supplies application instructions, service tools, approval rules, and persistence hooks.
Services own their external protocols and record rules.
Transport code owns message conversion and delivery.

`delegate_tasks` can run up to three research tasks.
Delegates receive search, weather, and skill tools.
They share the parent model-call budget and cannot create further delegates.
They receive no personal record or account tools.

### Persistence

| Data | Location | Restart behavior |
| --- | --- | --- |
| Conversations, context summaries, approvals, tool attempts | `theos.sqlite3` | Retained |
| Preferences, reminders, meals, training, account records | `theos.sqlite3` | Retained |
| Telegram inbox, polling offset, jobs, notifications | `theos.sqlite3` | Retained with recovery states |
| OAuth tokens | Encrypted fields in `theos.sqlite3` | Require the original encryption key |
| Private custom tables | `tables/` | Separate database per owner |
| Uploaded and generated files | `files/` and the SQLite catalog | Retained |
| Application events | `logs/theos.log` | Retained with file rotation |
| Tool traces and usage | SQLite tables | Retained without automatic pruning |
| External memory, R2 objects, remote sandboxes | External services | Depend on service policies |

Paths are relative to `AGENT_DATA_DIR`.
The local default is `.theos`.
Compose fixes the container path at `/data`.
Changing the assistant name does not rename stored data or deployment resources.

### Approvals and recovery

The runtime saves a tool attempt before the external call.
It saves the result before the next model request.
After a crash, incomplete attempts have unknown outcomes.
The runtime does not repeat them automatically.

Approvals bind to the tool, saved arguments, owner, session, expiry, and review contents.
They expire after 15 minutes.
Gmail also checks the draft contents before sending.
Another client can still edit the remote draft during that final request.
The [tool catalog](tool-catalog.md#approval-boundary) lists actions that need approval.

The scheduler saves reminder occurrences before delivery.
It skips missed recurring occurrences instead of sending a backlog.
Uncertain Telegram sends stay available for review.
Health jobs inspect named remote records before another export attempt.

### External service boundaries

Gmail, Google Health, and Zepto tools require authenticated browser or allowed private Telegram sessions.
Groups and standalone terminal sessions do not receive those tools.
Connected terminal clients authenticate as browser users and use the deployment's existing account-tool policy.
Memory requests carry owner scope. Explicit saves require user intent, and automatic consolidation requires approved per-user consent.
Ordinary chat continues when optional memory fails.

Remote sandboxes receive no application credentials or host mounts from Theos.
The operator controls the remote network and resource limits.
Theos does not deploy the memory, sandbox, or speech servers.

## Implementation status

The framework remains the architecture reference as implementation progresses.
General episodic retrieval, evaluation gates, and a general library facade remain future work.
Scheduled agent tasks and consented Mem0 consolidation are implemented, with live verification tracked separately.
The diagrams do not establish implementation or live service success.

Read the [code guide](code-structure.md), [diagram library](architecture/README.md), and [acceptance checklist](runtime/acceptance.md) for details.
