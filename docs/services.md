# External services

All integrations are optional except the selected model provider.
The application does not deploy memory servers, vector databases, embedding models, or speech models.
The current memory client supports Mem0 OSS. Mem0 Platform needs a separate adapter.
Use private service endpoints where possible.

## Service guides

| Service | Guide |
| --- | --- |
| Environment settings | [Configuration](base-infra/environment-variables.md) |
| External memory | [Memory](memory.md) |
| Remote execution | [Sandbox](sandbox.md) |
| Local files, R2, and audio | [Files and voice](files-and-voice.md) |
| Gmail | [Gmail](gmail.md) |
| Google Health | [Google Health](google-health.md) |
| Zepto tools | [Zepto MCP](zepto-mcp.md) |

## Models


For Gemini, set `AGENT_PROVIDER=gemini` and a Google AI Studio key.
For OpenRouter, set `AGENT_PROVIDER=openrouter` and an OpenRouter key.
Set `AGENT_MODEL` to a model ID accepted by that provider.

OpenRouter uses its [Chat Completions API](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request).
The application sends reasoning effort through OpenRouter's `reasoning` field.
OpenAI, Anthropic, and llama-server retain their existing harness adapters.
Provider-specific reasoning options require support from the selected model.
Use `default` when a model rejects an explicit reasoning option.

## Search, weather, and skills


Set `AGENT_EXA_KEY` for Exa search.
Set `AGENT_BRAVE_KEY` for Brave search or Exa failure fallback.
Weather uses the Open-Meteo geocoding and forecast APIs.

Set `AGENT_SKILLS_DIR` to an operator-controlled directory.
Each skill uses a subdirectory containing `SKILL.md`.
A skill can include text resources below that directory.
The loader rejects paths that escape the skill directory.
A skill supplies model instructions. It does not grant additional application permissions.

## Live acceptance

Mocked tests check application behavior and request formats.
They do not prove that a real account has service access or billing enabled.
Use the [live acceptance checklist](runtime/acceptance.md#live-service-checks) after service setup.
Do not mark a live test as passed from a mock result.
