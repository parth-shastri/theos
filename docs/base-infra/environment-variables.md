# Environment variables

Application settings use the `AGENT_` prefix.
Nested settings use two underscores.
Lists, sets, and maps use JSON values.
The [minimal sample](../../.env.minimal) supports a first start.
The [full sample](../../.env.full.example) includes optional services and Compose settings.

Source: [settings](../../src/theos/settings.py), [model defaults](../../src/theos/config.py), and [Compose](../../compose.yaml).

## Loading and precedence

The application reads `.env` from its working directory.
Process environment values override values in that file.
Explicit `Settings(...)` arguments override both during application construction.
A nested variable overrides the corresponding value in a parent JSON setting.
Unknown fields do not create application settings.

The tables below show application defaults.
Samples can choose different values, such as `Asia/Kolkata` instead of `UTC`.
Empty credentials mean that no credential exists.

For an older installation, replace `THEOS_` with `AGENT_` in environment variable names.
The old prefix is no longer read.
After a Compose environment change, recreate the container:

```sh
docker compose config --quiet
docker compose up -d --force-recreate
```

A process restart alone does not replace container environment values.

## Identity and browser access

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_NAME` | `Theos` | Assistant identity, browser labels, and Telegram greeting |
| `AGENT_USERS` | `{}` | Browser user IDs mapped to unique tokens |
| `AGENT_ADMINS` | `[]` | Browser user IDs with dashboard and log access |
| `AGENT_WEB_URL` | Empty | HTTPS deployment origin for Telegram-confirmed browser sign-in links |
| `AGENT_TIMEZONE` | `UTC` | Default timezone for personal records and reminders |

Names contain 1 to 100 characters after trimming surrounding whitespace.
The assistant name does not change the Telegram bot username or the package name.
Browser tokens need at least 32 characters.
Every administrator needs an entry in `AGENT_USERS`.
Configured browser IDs cannot start with `telegram:`, `telegram-group:`, or `terminal:`.
Keep browser IDs stable when rotating tokens.
Generated Telegram browser credentials use the enrolled sender's existing owner without editing `AGENT_USERS`.
`AGENT_WEB_URL` must be an HTTPS origin without a path, query, credentials, or fragment.
HTTP is allowed only for localhost development.

```dotenv
AGENT_NAME=Aster
AGENT_USERS={"owner":"replace-with-at-least-32-random-characters"}
AGENT_ADMINS=["owner"]
AGENT_TIMEZONE=Asia/Kolkata
```

The `display_name` preference names the user.
It does not replace `AGENT_NAME`.

## Terminal client connection

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_SERVER_URL` | Empty | Deployment URL for connected terminal mode, including a Tailscale or tunnel address |
| `AGENT_SERVER_TOKEN` | Empty | The same private token used for browser login |

These variables configure the terminal client. They do not change the deployment's bind address or user map.
`--server` overrides the URL. `--token-file` overrides the token. An empty token prompts interactively.
Use `--local` to run the standalone terminal despite a configured URL.
Connected mode uses server storage and never starts a local runtime or scheduler.
See the [terminal guide](../terminal.md#connect-to-a-deployment).

## Server and limits

| Variable | Default | Meaning or range |
| --- | --- | --- |
| `AGENT_HOST` | `127.0.0.1` | Local Python bind address |
| `AGENT_PORT` | `8080` | Local Python port, from 1 to 65535 |
| `AGENT_DATA_DIR` | `.theos` | Databases, local files, and logs |
| `AGENT_MAX_CONCURRENT_TURNS` | `4` | Concurrent turns, from 1 to 32 |
| `AGENT_MAX_MODEL_CALLS` | `30` | Optional bounded mode only. Total calls per turn, from 1 to 100 |
| `AGENT_MAX_COMPACTION_CALLS` | Unset; derived | Optional bounded mode only. Summary count, from 0 to 100. Zero disables summaries in bounded mode |
| `AGENT_COMPACTION_CALL_RATIO` | `1/6` | Fraction of total reserved for summaries when the count is absent, from 0 to 1. Round up |
| `AGENT_MAX_RECOVERY_CALLS` | `1` | Legacy setting accepted for compatibility. The runtime always reserves one final response call |
| `AGENT_DELEGATE_MAX_MODEL_CALLS` | Unset; derived | Optional explicit research and handoff ceiling per delegate, from 1 to 100 |
| `AGENT_DELEGATE_CALL_RATIO` | `1/3` | Fraction of total for each delegate ceiling when the count is absent, greater than 0 and at most 1. Round up |
| `AGENT_TURN_TIMEOUT` | `300` | Optional bounded mode only. Deadline for new research, from 10 to 3600 seconds |
| `AGENT_CONTEXT_TOKENS` | Unset | Optional context override, at least 4096 tokens and within known provider capacity |
| `AGENT_COMPACTION_TRIGGER_RATIO` | `0.5` | Configured trigger fraction, greater than zero and at most one. The policy applies its small-window floor |
| `AGENT_COMPACTION_MODEL` | `gpt-6-luna` | Auxiliary summary model. Other providers use their conversation model unless configured |
| `AGENT_COMPACTION_CONTEXT_TOKENS` | Unset | Optional auxiliary context capacity, at least 1024 tokens |
| `AGENT_COMPACTION_TAIL_MODE` | `lean` | Token-sized lean tail or a larger current tail. Both preserve complete tool exchanges |
| `AGENT_COMPACTION_MIN_TAIL_USER_MESSAGES` | `1` | Recent user messages retained in the tail, from 1 to 20. More messages can exceed the tail target |
| `AGENT_MAX_OUTPUT_TOKENS` | `8192` | Default output allowance. Explicit conversation output settings override it |
| `AGENT_MAX_UPLOAD_BYTES` | `10485760` | File limit, from 1024 to 26214400 bytes |

Compose overrides the host, port, and data directory with `0.0.0.0`, `8080`, and `/data`.
Use `HOST_BIND_IP` and `HOST_PORT` to change the host mapping.
Unset context uses the model capacity from provider metadata or the verified catalog.
Unknown models use a logged 24,000-token fallback unless the operator configures a window.
The context override does not increase the selected model's capacity.
Pi uses `AGENT_CONTEXT_TOKENS=100000` and `AGENT_MAX_OUTPUT_TOKENS=8192`.
The default policy starts compaction at 68,856 input tokens for this Pi cap and output reservation.
Theos disables call budgets and research deadlines by default. Summary calls still enter usage records.
An explicit trigger ratio overrides the default. Output reservations can require earlier compaction.
Compaction starts at 70 percent by default and targets 45 percent after a complete summary.

Omitted counts derive from the total using the configured ratios, rounded up.
Explicit counts override their own ratios. Remove old explicit counts to enable automatic derivation.
The default total of 30 gives 24 research calls, five summary calls, and one parent response call.
A total of 50 gives 40 research calls, nine summary calls, and one parent response call.
The delegate ceiling grows from ten to 17 research and handoff calls.
It is bounded by shared research capacity. Summary allocation also retains one research slot on small totals.
Settings are resolved once per turn. Recreate the container after changing environment variables.
The parent and delegates share research calls. Title generation also uses this allowance.
Each delegate reserves a handoff call before research starts. Its derived ceiling includes that response.
Delegate summaries count toward the shared total, outside its research and handoff ceiling.
Compaction uses its reserved allowance without consuming research calls.
Unused compaction calls stay reserved. They do not extend research.
Each summary chunk consumes one compaction call, including failed provider requests.
Compaction usage enters the same usage records as ordinary model requests.

On research exhaustion, the runtime requests one final response without tools or a generation deadline.
A failed final response returns a clear error without retrying. Saved findings remain in the transcript.
The legacy recovery setting no longer changes the single-attempt rule.
Small total limits reduce compaction reserves first.
A total limit of one reserves the final response and starts no research.
Set the compaction allowance to zero to disable model-based compaction.
The request must still fit the configured context window.
The delegate deadline remains 85 seconds. The turn deadline remains 300 seconds by default.

## Models and cost estimates

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_PROVIDER` | `openai` | `openai`, `openrouter`, `gemini`, `anthropic`, `llama`, or `fake` |
| `AGENT_MODEL` | `gpt-6-luna` | Default provider model ID |
| `AGENT_API_KEY` | Empty | Credential for the selected provider |
| `AGENT_MODEL_BASE_URL` | Empty | Base URL override for the OpenAI client path |
| `AGENT_ALLOWED_MODELS` | `[]` | Explicit model allowlist. Empty uses the provider's built-in choices and `AGENT_MODEL` |
| `AGENT_REASONING` | `default` | `default`, `none`, `low`, `medium`, `high`, `xhigh`, or `max`, where supported |
| `AGENT_OPENROUTER__SORT` | `latency` | Prefer latency, throughput, or price among eligible endpoints |
| `AGENT_OPENROUTER__ORDER` | `[]` | Preferred endpoint slugs in order. Other eligible providers remain fallbacks |
| `AGENT_OPENROUTER__LATENCY_P90` | `15` | Prefer endpoints whose recent p90 latency is at most this many seconds |
| `AGENT_OPENROUTER__THROUGHPUT_P90` | `10` | Prefer endpoints whose recent p90 throughput is at least this many tokens per second |
| `AGENT_AUTO_TITLES` | `true` | Generate browser conversation titles from opening exchanges. Title usage contributes to conversation costs |
| `AGENT_INPUT_COST_PER_MILLION` | Unset | Nonnegative input rate in USD per million tokens |
| `AGENT_OUTPUT_COST_PER_MILLION` | Unset | Nonnegative output rate in USD per million tokens |
| `AGENT_MODEL_COSTS` | `{}` | Per-model USD rates with `input` and `output` fields. These override the shared rates |

OpenAI uses Responses. OpenRouter uses Chat Completions.
The llama provider defaults to `http://127.0.0.1:8081/v1`.
Gemini and Anthropic use their dedicated clients.
`AGENT_MODEL_BASE_URL` applies to OpenAI, OpenRouter, and llama.

All real hosted providers require `AGENT_API_KEY` for model calls.
The fake provider needs no credential.
The llama client uses a local placeholder when the key is empty.
A model must support the requested reasoning option.
Use `default` when the provider rejects an explicit effort.

OpenRouter preferences apply to chat, research, compaction, and title requests.
They retain `provider.zdr=true`, saved signed reasoning, and explicit request preferences.
Performance thresholds deprioritize slow endpoints. They are not request deadlines or hard exclusions.
Pi prefers `AGENT_OPENROUTER__ORDER=["azure/eu"]` after its measured base Azure stalls.
An incompatible preferred endpoint does not disable other eligible providers.
Do not disable ZDR to reach a faster endpoint.

OpenRouter-reported costs take precedence over configured estimates.
Both cost rates must exist before Theos records a token-rate estimate.
The rates apply across configured models.
Use `AGENT_MODEL_COSTS` when model rates differ.
Keys can use a configured alias or its OpenRouter model ID.
The estimate does not include provider billing adjustments or a separate cached-token rate.

OpenRouter includes `gpt-5.6-luna`, `sonnet-5.5`, `deepseek-flash-v4.1`, `gemini-3.8-flash`, `glm-5.3-flash`, and `qwen-3.8-27b`.
The existing `gpt-6-luna` default remains available.
Direct OpenAI adds only `gpt-5.6-luna` to its configured model.
Other providers use the configured model unless an operator supplies an allowlist.
Browser generation controls use a provider capability snapshot and save per conversation.
Set `AGENT_MAX_OUTPUT_TOKENS` in `.env` for the default output allowance.
Conversation generation controls can override this value.
Without an override, requests use 8,192 output tokens, bounded by the known provider maximum.
The `gpt-6-luna` catalog fallback is 128,000 output tokens. OpenRouter metadata can update this value.
Space checks reserve that output allowance before summarizing input. They do not silently lower the setting.
Smaller context overrides must still accommodate the requested output and the preserved task.
Calls without a known output setting share the 8,192-token space estimate defined in `harness/output.py`.
This estimate does not change provider generation settings or shorten returned answers.
A context override smaller than this estimate needs an explicit conversation output setting.

## Telegram

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_TELEGRAM_TOKEN` | Empty | Bot token. A nonempty value enables polling |
| `AGENT_TELEGRAM_ACCESS_CODE` | Empty | Shared onboarding password. Set per deployment in private `.env` |
| `AGENT_TELEGRAM_USERS` | `[]` | Optional sender allowlist. Empty permits registration through the bot |
| `AGENT_TELEGRAM_MAX_USERS` | `50` | Maximum registered Telegram users, including incomplete setup. Range: 1 to 50 |
| `AGENT_TELEGRAM_CHATS` | `[]` | Allowed group or supergroup IDs |

A configured token enables polling and private `/start` onboarding.
Group access requires completed private onboarding and an allowed chat ID.
A nonempty sender allowlist restricts registration and all Telegram chat access.
With an access code, users must send `/start <access-code>` before onboarding or chat.
Without an access code, registration is public within the user limit.
SQLite stores authorization fingerprints and enrollment state, without the plaintext code.
Code changes require authorization again and preserve existing records.
Completed enrollment permits private account connections without a manual sender allowlist.
See [Telegram setup](../telegram-setup.md).

## Memory

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_MEMORY__ENABLED` | `false` | Register external memory tools |
| `AGENT_MEMORY__ENDPOINT` | `http://127.0.0.1:8001` | Mem0 REST service base URL |
| `AGENT_MEMORY__API_KEY` | Empty | Service credential |
| `AGENT_MEMORY__TIMEOUT` | `15` | Request seconds, greater than zero and at most 120 |
| `AGENT_MEMORY__AUTH_HEADER` | `X-API-Key` | `X-API-Key` or `Authorization` |
| `AGENT_MEMORY__AUTH_PREFIX` | Empty | Credential prefix, such as `Bearer ` |
| `AGENT_MEMORY__AUTO_RETRIEVE` | `true` | Default private-chat retrieval policy when memory is enabled |
| `AGENT_MEMORY__RETRIEVAL_LIMIT` | `5` | Maximum facts per turn, from 1 to 20 |
| `AGENT_MEMORY__RETRIEVAL_CHARS` | `4000` | Fact text budget, from 256 to 16000 characters |
| `AGENT_MEMORY__RETRIEVAL_TIMEOUT` | `3` | Retrieval deadline in seconds, at most 15 |
| `AGENT_MEMORY__CONSOLIDATION_TURNS` | `5` | Consented queued-message threshold, from 1 to 50 |
| `AGENT_MEMORY__CONSOLIDATION_INTERVAL` | `600` | Partial-batch wait in seconds, from 10 to 86400 |

See [memory](../memory.md) for endpoint and ownership requirements.

Consolidation also requires per-user opt-in through `configure_memory_automation`.
`AGENT_MAX_SCHEDULED_TASKS` defaults to 50 pending or paused tasks per owner, with a range of 1–200.
See [scheduled tasks](../scheduled-tasks.md) for execution and delivery behavior.

## Search, weather, and skills

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_EXA_KEY` | Empty | Exa search credential |
| `AGENT_BRAVE_KEY` | Empty | Brave search credential and fallback |
| `AGENT_SKILLS_DIR` | Unset | Directory containing skill subdirectories |

Weather uses Open-Meteo without an application credential setting.
Search needs at least one configured search credential.
Skills use `SKILL.md` and optional text resources within each skill directory.
See [external services](../services.md#search-weather-and-skills).

## Sandbox

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_SANDBOX__ENABLED` | `false` | Register remote sandbox tools |
| `AGENT_SANDBOX__DOMAIN` | `localhost:8080` | OpenSandbox server address |
| `AGENT_SANDBOX__API_KEY` | Empty | Server credential |
| `AGENT_SANDBOX__USE_SERVER_PROXY` | `false` | Route sandbox execution and file requests through the server. Enable for remote hosts over Tailscale |
| `AGENT_SANDBOX__IMAGE` | `opensandbox/code-interpreter:v1.0.1` | Remote sandbox image |
| `AGENT_SANDBOX__TIMEOUT_SECONDS` | `3600` | Lifetime from creation, from 60 to 3600 seconds. Reads and renew calls do not extend it |

Container loopback refers to the assistant container.
Set a server address that the container can reach.
See [sandbox](../sandbox.md) for browser dependencies and lifecycle operations.

## Files and voice

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_STORAGE__ENDPOINT` | Empty | R2 S3-compatible endpoint |
| `AGENT_STORAGE__BUCKET` | Empty | Private bucket |
| `AGENT_STORAGE__ACCESS_KEY` | Empty | Bucket access key |
| `AGENT_STORAGE__SECRET_KEY` | Empty | Bucket secret key |
| `AGENT_TRANSCRIPTION_URL` | Empty | Transcription base URL |
| `AGENT_TRANSCRIPTION_KEY` | Empty | Transcription bearer credential |
| `AGENT_TRANSCRIPTION_MODEL` | `whisper-1` | Transcription model ID |
| `AGENT_KOKORO_URL` | Empty | Speech service base URL |
| `AGENT_KOKORO_VOICE` | `af_heart` | Speech voice |

Configure all four storage fields together.
Voice URLs include `/v1` when the service requires it.
The client appends `/audio/transcriptions` or `/audio/speech`.
See [files and voice](../files-and-voice.md).

## Google accounts

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_GMAIL__CLIENT_ID` | Empty | Gmail OAuth client ID |
| `AGENT_GMAIL__CLIENT_SECRET` | Empty | Gmail OAuth client secret |
| `AGENT_GMAIL__REDIRECT_URI` | Empty | Exact Gmail callback URI |
| `AGENT_HEALTH__CLIENT_ID` | Empty | Google Health OAuth client ID |
| `AGENT_HEALTH__CLIENT_SECRET` | Empty | Google Health OAuth client secret |
| `AGENT_HEALTH__REDIRECT_URI` | Empty | Exact Google Health callback URI |
| `AGENT_TOKEN_ENCRYPTION_KEY` | Empty | Fernet key for Gmail, Health, and Zepto account tokens |
| `AGENT_HEALTH_INTERVAL` | `43200` | Import interval in seconds, at least 60 |

OAuth means Open Authorization.
Each service requires its own complete set of three client fields.
Browser and private Telegram users authorize separate owner-bound accounts.
Browser users connect through **Connections**. Telegram users use their account commands.
The application does not infer callback URIs.
A configured service also requires a valid Fernet key.
HTTPS callbacks are required except for HTTP on `localhost` or `127.0.0.1`.

See [Gmail](../gmail.md) and [Google Health](../google-health.md).

## Zepto

| Variable | Default | Meaning |
| --- | --- | --- |
| `AGENT_ZEPTO_URL` | Empty | Trusted Streamable HTTP MCP endpoint |
| `AGENT_ZEPTO_REDIRECT_URI` | `http://localhost/callback` | Registered local or public HTTPS OAuth callback URI |

Model Context Protocol (MCP) connects the application to remote tools.
Each private Telegram user connects their own Zepto account with `/connect_zepto`.
Browser users connect their own account through **Connections > Zepto**.
The endpoint and a valid encryption key must exist before account linking.
Use HTTPS for a public endpoint and public callback URI.
Use the default localhost callback when the application cannot receive public inbound traffic.
See [Zepto MCP](../zepto-mcp.md) for external authorization and approval rules.

## Docker Compose variables

These settings control Compose rather than the Python settings model.

| Variable | Default | Meaning |
| --- | --- | --- |
| `HOST_BIND_IP` | `127.0.0.1` | Host interface for browser access |
| `HOST_PORT` | `8080` | Published host port |
| `AGENT_IMAGE` | `theos:local` | Built or selected image reference |
| `AGENT_DATA_VOLUME` | `theos-data` | Named volume mounted at `/data` |
| `AGENT_MEMORY_LIMIT` | `768m` | Container memory limit |
| `AGENT_CPU_LIMIT` | `1.0` | Container CPU limit |

Shell variables can override Compose interpolation from `.env`.
The service always reads its container environment from `.env` plus explicit Compose overrides.
A different `--env-file` does not change the service `env_file: .env` declaration.
See the [Compose workflow](docker-compose-workflow.md) before changing that behavior.

## Credentials

Keep `.env` outside source control and restrict it to the operator.
Do not paste credentials into chat or a sandbox.
Use `docker compose config --quiet` for routine configuration checks.
The full resolved configuration can contain credentials.
Back up the token encryption key with the matching application data.

The parent holds one summary call for its final response within the summary allowance.
Each active delegate holds one when available. Completed delegates release unused holds.
These holds do not add calls or change the generation output setting.
See the [call budget map](../runtime/call-budgets.md).
