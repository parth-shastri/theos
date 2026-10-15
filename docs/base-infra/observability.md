# Observability

Theos records application events, tool traces, and model usage locally.
Optional OpenTelemetry tracing exports one trace per turn through OTLP/HTTP protobuf.

OpenRouter can reject saved encrypted reasoning when its required endpoint conflicts with zero data retention.
The adapter retries that routing rejection once without the affected reasoning sequences, before generation starts.
It preserves ZDR, visible history, tool exchanges, and request options.
The log event `openrouter_reasoning_replay_rejected` records this recovery without private content.
For OpenAI models, each request replays only the latest known provider format of encrypted reasoning.
The adapter omits incompatible sequences from the wire request and retains saved messages and signed blocks.
It also retries a mixed-provider HTTP 400 once before generation, without incompatible reasoning.
The event `turn_incomplete` records a turn that needs finalization.
The call budget counts harness model calls. SDK retries and this bounded routing retry are transport attempts within those calls.
The application log formatter excludes prompts, credentials, and remote error bodies.
Conversation history remains private data in SQLite and needs separate protection.

Model spans also record the actual output allowance and explicit reasoning effort, or `provider_default` when omitted.
They record serialized request bytes, input message count, tool schema count, and validated routing controls.
These fields exclude prompt text, tool schemas, credentials, and arbitrary request options.
OpenRouter reasoning-token usage appears as `gen_ai.usage.reasoning.output_tokens` when reported.
Reasoning tokens are part of total output tokens. They are not billed or counted again.

## Outputs

| Output | Location | Contents |
| --- | --- | --- |
| Application events | `AGENT_DATA_DIR/logs/theos.log` | Fixed event names, timestamps, levels, and selected metadata |
| Runtime traces | `traces` table in `theos.sqlite3` | Owner, session, event, tool name, status, and timestamp |
| OpenTelemetry spans | Configured OTLP endpoint | Turn, model, tool, delegate, and title timing with token counts and status |
| Model usage | `usage` table in `theos.sqlite3` | Owner, session, model, token counts, and optional cost estimate |
| Conversation state | `sessions` and related SQLite tables | Messages, tool arguments, results, and approval state |
| Container output | Docker logging driver | Process and HTTP server output |

Compose stores application data under `/data`.
Application events use a file handler and do not propagate to container output.
The server suppresses verbose harness and external client loggers.

## Read application events

```sh
docker compose exec theos python -c   'from pathlib import Path; print(Path("/data/logs/theos.log").read_text()[-16000:])'
```

| Event | Meaning |
| --- | --- |
| `started` | Application workers entered their lifespan |
| `turn_incomplete` | A turn reached a limit or raised an exception before its final answer |
| `delegate_incomplete` | One delegate stopped and returned available findings |
| `final_answer_unavailable` | The bounded final request failed, so the runtime returned saved findings |
| `integration_unavailable` | Optional integration discovery failed |
| `telegram_update_failed` | An accepted Telegram update failed |
| `notification_failed` | Reminder delivery failed or has an uncertain outcome |
| `scheduler_failed` | Scheduled work raised an exception |
| `trace_export_failed` | Remote trace delivery failed |

The formatter permits `error_type` and `session_id` metadata.
It does not include exception text or stack traces.
A generic error type can require a separate service check.

## Private dashboard

1. Configure a browser token in `AGENT_USERS`.
2. Add that user ID to `AGENT_ADMINS`.
3. Sign in through the browser page.
4. Open **Admin dashboard**.

`GET /api/dashboard` requires an administrator token.
It returns users, recent sessions, usage totals, recent traces, recent jobs, and the last scheduler tick.
`GET /api/logs` returns up to 100 recent application events.
There is no separate `/dashboard` page.

## View a trace waterfall

Use Jaeger v2 for a private waterfall viewer.
Its single-node Badger storage requires no separate database and retains traces across restarts.
The supplied configuration keeps spans for seven days.
See the [Jaeger storage documentation](https://www.jaegertracing.io/docs/2.22/storage/badger/).

1. Start Theos and Jaeger from the repository root.

   ```sh
   docker compose -f compose.yaml -f compose.tracing.yaml up --build -d
   ```

2. Open [Jaeger](http://127.0.0.1:16686).
3. Send a new message through Telegram, the browser, or the connected terminal.
4. Select service **theos** in Jaeger.
5. Select **Span Name → invoke_agent Theos** and find traces.
6. Open a trace to inspect the waterfall.

The operation uses the configured assistant name when it differs from `Theos`.
The browser Admin dashboard still shows SQLite events. Jaeger shows the span waterfall.
Old SQLite events do not become OTel traces.

Each turn starts a new root trace, including approval continuation and scheduled turns.
Every span includes the existing `gen_ai.conversation.id` and its `theos.turn.id`.
The root also includes transport, scheduled state, and final status.
Root attributes `theos.budget.total`, `theos.budget.research`, `theos.budget.compaction`, and `theos.budget.recovery` each have `.limit` and `.used` values.
They show reserved allowances and consumed calls, including title generation and failed provider attempts.
Model spans record `theos.model.reasoning_effort` and these stream timings:

- `gen_ai.response.time_to_first_chunk`
- `theos.model.time_to_first_reasoning_chunk`
- `theos.model.time_to_first_text_chunk`
- `theos.model.time_to_first_tool_call_chunk`
- `theos.model.time_to_last_text_chunk_seconds`
- `theos.model.time_to_response_complete_seconds`

OpenAI Responses spans also record reasoning token counts when the provider reports them.
The value `default` means that the provider chose the reasoning effort.
Each turn span records these timing attributes:

- `theos.turn.duration_seconds`: elapsed time from query acceptance to turn finalization.
- `theos.turn.time_to_first_model_call_seconds`: elapsed time until the first model request starts.
- `theos.turn.time_to_first_stream_chunk_seconds`: elapsed time until the first streamed model chunk.
- `theos.turn.time_to_first_reasoning_chunk_seconds`: elapsed time until the first reasoning chunk.
- `theos.turn.time_to_first_text_chunk_seconds`: elapsed time until the first response text chunk.
- `theos.turn.time_to_last_text_chunk_seconds`: elapsed time until the last response text chunk.

Time to first model call includes lock waits and request preparation.
Use per-model chunk times to measure provider latency after each request starts.
Providers send stream chunks, so these values do not measure individual tokenizer tokens.
Delegate spans include `theos.delegate.model_calls.limit` for the configured local cap.
Use `gen_ai.conversation.id` in Jaeger's **Attributes** filter to find turns from one conversation.

OpenTelemetry defines a conversation identifier, but it does not require one trace for an entire conversation.
Its [GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md) use that identifier to correlate operations.
These conventions remain in development.
[Langfuse sessions](https://langfuse.com/docs/observability/features/sessions) also group multiple traces into one interaction.

Theos uses one trace per turn because each turn has a clear start, result, and cancellation boundary.
A conversation can remain idle for days and continue after a restart.
A conversation root would include that idle time and require a separate lifecycle policy.
Jaeger searches related turn traces by attribute. It does not provide a dedicated conversation replay page.

Model calls and executed tools are children of the turn.
Each research delegate is a child of `execute_tool delegate_tasks`.
Each delegate owns its model calls and read-only tool calls.
Parallel delegates appear as separate branches with overlapping timings.
Model spans also cover context summaries. Title generation has a separate `generate_title` span.
Approval requests and policy denials create tool spans without executing the tool.

Limit recovery adds a `finalize answer` span with `theos.recovery.reason` and `theos.recovery.mode`.
The mode identifies a final model request, an existing answer, or saved findings.
Any final model request appears beneath this span and has no tools.
The turn records `partial` status when it returns useful findings.
If finalization has no useful output, it returns a clear failure and records `failed` status.
The finalization span then records `theos.recovery.mode=failure` and a `no_answer` error.
An uncertain external action retains `uncertain` trace status and requires review.
Partial delegates expose their status and recovery reason. Completed sibling findings remain available to the parent.
Model-visible tool copies have character limits separate from the OTel capture limits below.
The runtime retains full durable tool results and does not repeat tools during recovery.

![Tracing and span ownership](../architecture/theos-tracing.png)

The exporter sends model names, tool names, call IDs, token counts, timings, status, and exception types.
Content capture is disabled by default. Set `AGENT_TRACING__CAPTURE_CONTENT=true` to include messages and tool content.
Captured traces contain private conversation data. Keep the receiver private.

| Attribute | Captured content |
| --- | --- |
| `gen_ai.system_instructions` | Model instructions as JSON text parts |
| `gen_ai.input.messages` | Model inputs, including earlier tool requests and results, as JSON roles and parts |
| `gen_ai.output.messages` | Model replies and tool requests, with names, arguments, and call IDs |
| `gen_ai.tool.call.arguments` | Validated tool arguments as JSON |
| `gen_ai.tool.call.result` | Successful tool results as JSON |
| `gen_ai.agent.name` | Parent or delegate name, also inherited by its model and tool spans |

Each captured field permits 8,192 UTF-8 JSON bytes by default. Each span permits 32,768 captured bytes in total.
The serializer bounds nesting, item counts, and traversal before encoding. It preserves valid JSON when content exceeds a limit.
`theos.content.truncated=true` identifies shortened fields or omitted messages. Model input capture retains at most the latest 32 messages in order.
The serializer masks structured credential fields. This does not remove sensitive information from arbitrary prose.
Capture excludes reasoning, image payloads, provider state, authentication headers, owner IDs, and exception text.
Failed tool messages retain their status without their error payload.

Pass named assignments to `delegate_tasks`, for example `{"tasks":[{"name":"Mumbai Weather Analyst","task":"Compare the three-day forecast"}]}`.
The delegate span uses `invoke_agent Mumbai Weather Analyst` and records its task and final answer when capture is enabled.
The delegate result includes its name. Legacy string assignments remain supported with names such as `research 1`.
Agent names follow the [OTel GenAI agent conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md).
No transient process identifier is exported as `gen_ai.agent.id`.
The exporter does not write local OTLP/JSON files.
SQLite events and usage remain available when remote tracing is disabled.

The Compose viewer and receiver bind to host loopback.
Jaeger access is separate from Theos administrator authentication.
The current setup has no Jaeger password, user accounts, or per-user trace isolation.
Anyone who can reach the viewer can inspect every stored trace, including captured conversation content.
Treat the viewer as an operator tool. Theos browser tokens do not protect its UI or query API.
Local access, authenticated SSH tunnels, and Pi Tailscale Serve control network access. They do not filter traces by owner.
A reverse proxy can add login protection, but login alone does not enforce per-user trace ownership.
User-facing trace access needs a separate layer that checks conversation ownership. This layer is not implemented.
For a remote host, use private access or an SSH tunnel.

```sh
ssh -L 16686:127.0.0.1:16686 your-host
```

Use both Compose files for later lifecycle commands.
The `jaeger-data` volume is separate from application data and application backups.
The named volume has no hard disk limit. Badger expires spans after seven days.
Background maintenance reclaims expired data. Monitor volume growth separately.

## Pi viewer through Tailscale Serve

Connect your Mac to Tailscale and open [Pi Jaeger](https://neuralbox-pi.tail61f0ca.ts.net:8443/).
Select service **theos** and find traces. Existing trace links also work with this hostname and port.
The viewer uses your Tailscale device identity. You do not need an SSH port forward or a Jaeger password.
The operator group currently contains `parth-shastri@github`.
All allowed operators can inspect all stored traces, including captured conversation content.

The Pi runs Tailscale `1.102.4` on the host.
Serve terminates HTTPS on the Pi tailnet addresses and proxies `http://127.0.0.1:16686`.
The `--bg` configuration persists across restarts.
The host loopback bindings for Jaeger and OTLP remain unchanged.
Serve exposes only the viewer. It does not expose OTLP port 4318.
This endpoint uses private Serve, without public Funnel access.
See [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

The [policy snapshot](../../config/tailscale/pi-jaeger.policy.json) records the applied tailnet policy and seven access tests.
It is not an automatic policy synchronization mechanism.
Review the current tailnet policy before reapplying this snapshot, to preserve later changes.

The former wildcard grant allowed every device to reach every port.
Tailscale grants are additive. An operator grant cannot override an existing wildcard grant.
The current policy excludes both Pi IP addresses from the broader grant.
Separate grants retain other Pi TCP ports, UDP, and ICMP.
Only `group:theos-operators` receives Pi TCP 8443.
The four `/1` prefixes cover both address families before the IP set removes the Pi addresses.
The test aliases are unassigned addresses for nonoperator policy checks, not enrolled devices.
The existing SSH policy and Funnel capability attributes remain unchanged.
A Funnel capability does not create a public endpoint. The Pi Serve configuration has no Funnel listener.
See [grants](https://tailscale.com/docs/reference/syntax/grants) and [policy tests](https://tailscale.com/docs/reference/syntax/policy-file#tests).

To configure another deployment:

1. Confirm the host's Tailscale IPv4 and IPv6 addresses.
2. Set the operator group to the approved operator identities.
3. Exclude the viewer's TCP port from all broader grants that match the host.
4. Add operator allow tests and nonoperator deny tests for both IP families.
5. Save the policy after all Tailscale tests pass.
6. Enable the private HTTPS proxy on the host.

   ```sh
   sudo tailscale serve --bg --https=8443 http://127.0.0.1:16686
   ```

7. Check the persistent proxy configuration.

   ```sh
   tailscale serve status --json
   ```

8. Verify HTTPS from an operator device with certificate validation enabled.

   ```sh
   curl --fail https://neuralbox-pi.tail61f0ca.ts.net:8443/api/v3/services
   ```

To add an operator, update `group:theos-operators` in the Tailscale admin console and save after the policy tests pass.
Update this snapshot with the reviewed policy. Do not add a wildcard grant for Pi TCP 8443.
If the Pi's Tailscale addresses change, update the grant destinations, IP set exclusions, and policy tests together.

To disable this viewer endpoint, run the following command on the Pi:

```sh
sudo tailscale serve --https=8443 off
```

Keep the operator restriction in place when disabling Serve.
Restore the former policy only after the listener is disabled, if a full rollback is required.
The Jaeger container, trace volume, and seven-day retention do not require changes.
The existing SSH tunnel remains available as a private alternative.

## Export to another backend

The `server` extra includes the OTel SDK and OTLP/HTTP exporter.
Standalone terminal mode uses the same tracing settings.
Connected terminal mode sends turns to the server. Configure tracing on that server.

Without the Jaeger Compose override, configure these values in the server's private `.env`:

```dotenv
AGENT_TRACING__ENABLED=true
AGENT_TRACING__ENDPOINT=http://127.0.0.1:4318/v1/traces
AGENT_TRACING__SERVICE_NAME=theos
AGENT_TRACING__SAMPLE_RATIO=1
AGENT_TRACING__TIMEOUT=5
AGENT_TRACING__CAPTURE_CONTENT=false
AGENT_TRACING__CONTENT_MAX_BYTES=8192
AGENT_TRACING__SPAN_CONTENT_MAX_BYTES=32768
AGENT_TRACING__HEADERS={}
```

The endpoint is the complete trace URL, including `/v1/traces` or the backend's equivalent path.
For authenticated endpoints, set secret headers through `AGENT_TRACING__HEADERS`.
For example, use `{"Authorization":"Bearer your-token"}` in the private configuration.
The Jaeger Compose override selects `http://jaeger:4318/v1/traces` inside the container network.
For another receiver, omit that override and set the receiver's address.

Sampling defaults to every turn. A lower ratio selects whole traces, preserving their child hierarchy.
Tracing defaults to disabled and does not replace the process-wide OTel provider.
The exporter uses a background worker, a 2,048-span queue, and batches of at most 256 spans.
Graceful runtime shutdown drains the queue. Backend failures do not fail assistant turns.
An unavailable backend, a full queue, or a process crash can lose remote spans.
Remote trace export is best effort, not a durable replay queue.
Application logs record `trace_export_failed` with a safe error type when export fails.

To check a receiver without a model API request, run the disposable fake-model turn:

```sh
uv run --extra server python scripts/check_tracing.py
```

The script prints a trace ID and viewer URL.
Use `--endpoint` and `--viewer` for different receiver and UI addresses.

## Usage and cost

Model checkpoints record input, output, and cached input token counts.
Cost stays absent until both configured rates exist.

```dotenv
AGENT_INPUT_COST_PER_MILLION=0.10
AGENT_OUTPUT_COST_PER_MILLION=0.40
```

These values are illustrative, not current model prices.
Set rates appropriate for your deployment.
The calculation is input tokens times the input rate plus output tokens times the output rate, divided by one million.
Rates apply to all configured models.
The estimate does not represent an invoice or separate cached-token pricing.

## Retention

| Data | Policy | Enforcement |
| --- | --- | --- |
| Application log | 2,000,000 bytes per file, three backups | At most about 8 MB across four files |
| Application log age | Rotate the current file after seven days. Remove backups with modification times older than seven days | Startup, rotation, and hourly checks when the handler emits events |
| Container output | 5 MB per file, three files per container | Docker logging driver |
| Export queue | 2,048 spans, batches of 256 | SDK discards queued spans on overflow rather than growing without a limit |
| Jaeger spans | Seven-day expiry | Badger TTL and background maintenance |
| Jaeger memory | 512 MiB container limit, 300 MiB Go memory target | A limiter refuses ingestion above its 320 MiB soft heap threshold. Batches contain at most 256 spans |
| Jaeger storage | Persistent named volume with no hard size cap | Seven-day span expiry and background maintenance |
| SQLite events, usage, and conversation state | Keep existing records | No automatic deletion in this change |

These policies keep logs on disk and bound the queue in memory.
File age applies to whole files, not individual log records.
An idle process removes expired backups when logging resumes.
Monitor SQLite growth separately. Retained database pages do not imply that all rows reside in process memory.
The backup command excludes application logs.
Archive required diagnostic evidence separately before a restore or cleanup.

## Planned operations framework

![Operations framework](../architecture/theos-operations.png)

This diagram includes planned evaluation and release feedback paths.
The current application implements local logs, tool traces, usage records, and acceptance checks.
It also implements optional per-turn OpenTelemetry spans and an OTLP/HTTP exporter.
The complete evaluation cycle remains planned.

Source: [tracing](../../src/theos/operations/tracing.py), [logging](../../src/theos/operations/logging.py), [usage](../../src/theos/runtime/usage.py), and [browser APIs](../../src/theos/transports/browser/app.py).

## Diagnose turn latency and provider failures

A short HTTP request does not establish a short model generation.
OpenRouter can return headers before the first model token.
Compare the complete model span with `gen_ai.response.time_to_first_chunk` and each `provider HTTP request` span.

| Span | Measurement |
| --- | --- |
| `runtime wait` | Conversation lock and application concurrency wait |
| `runtime restore` | Local history and saved-result restoration |
| `runtime model capacity` | Cached or remote model capacity lookup |
| `runtime tool registry` | Tool schemas and optional connector discovery |
| `runtime memory retrieval` | Bounded Mem0 retrieval |
| `checkpoint persist` | Durable local checkpoint, with its stage |
| `provider HTTP request` | One HTTP attempt through response headers |
| `chat <model>` | Complete generation and first model event |
| `checkpoint upload`, `checkpoint publish` | Background object transfer and recovery-pointer publication |

Background checkpoint spans have separate traces and the conversation ID.
They do not inherit the turn that first queued storage work.
Application logs record `provider_request_failed`, `provider_stream_retry`, and `checkpoint_replication_failed`.
Provider fields include validated request IDs, status codes, known provider names, and allowlisted error classifications.
Unknown fields and raw provider prose are excluded, even when content capture is enabled.

OpenRouter may accept an HTTP request with 200 and later report 502 inside its stream.
Read `theos.provider.http_status` and `theos.provider.status_code` separately.
A valid generation ID supports a provider-side lookup, but failed generations may have no retained record.
A 502 alone does not prove overload, disconnection, or timeout.
The old Pi failure lost its detailed error metadata and cannot establish that distinction.

Transient accepted OpenRouter streams receive at most two additional attempts before any model event.
Additional attempts start only within the first 30 seconds, so a long failed generation does not start more long waits.
The runtime sends the same unfinished request, preserves ZDR, and keeps completed tool results.
Partial text, reasoning, and tool arguments stop this retry path.
Authentication, invalid requests, quota failures, and context errors retain their separate recovery paths.

![Durable local recovery and background replication](../architecture/theos-runtime-recovery.png)
