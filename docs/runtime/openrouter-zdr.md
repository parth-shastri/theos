# OpenRouter ZDR verification

Checked on 2026-10-10 against the [OpenRouter ZDR endpoint list](https://openrouter.ai/api/v1/endpoints/zdr).
Standalone requests used the local OpenRouter credential without application history or personal data.
Each request asked for `OK`, used `reasoning.effort=low`, and limited output to 512 tokens.

## Automatic routing

All seven models returned HTTP 200 with `provider.zdr=true`.
The returned provider names were:

| Theos model | Provider |
| --- | --- |
| `gpt-6-luna` | Azure |
| `gpt-5.6-luna` | Azure |
| `sonnet-5.5` | Google |
| `deepseek-flash-v4.1` | DigitalOcean |
| `gemini-3.8-flash` | Google |
| `glm-5.3-flash` | Together |
| `qwen-3.8-27b` | DekaLLM |

## Explicit provider routes

Each request used one listed provider tag in `provider.only`, with `provider.zdr=true` and `provider.allow_fallbacks=false`.
Duplicate tags for the same model were tested once.
Base provider tags can match endpoint variants under OpenRouter's routing rules.

| Theos model | Tested routes | HTTP 200 | HTTP 429 |
| --- | ---: | ---: | ---: |
| `gpt-6-luna` | 3 | 3 | 0 |
| `gpt-5.6-luna` | 3 | 3 | 0 |
| `sonnet-5.5` | 4 | 4 | 0 |
| `deepseek-flash-v4.1` | 25 | 21 | 4 |
| `gemini-3.8-flash` | 3 | 3 | 0 |
| `glm-5.3-flash` | 28 | 27 | 1 |
| `qwen-3.8-27b` | 15 | 15 | 0 |
| Total | 81 | 76 | 5 |

The following routes returned HTTP 429 with a provider error:

- `deepseek-flash-v4.1`: `baseten/fast`, `baseten/fp8`, `fireworks`, and `open-inference/fp4`.
- `glm-5.3-flash`: `baseten/fp8`.

These failures do not establish a ZDR incompatibility. Their inference availability remains unverified.
The successful requests reported a combined cost of USD 0.002564344 for the completed 88-request run.
This amount excludes the initial interrupted probe.

## Rejection check

A request for `openai/gpt-6-luna` forced `provider.only=["openai"]` with ZDR enabled and fallbacks disabled.
OpenRouter returned HTTP 404 because no endpoint matched the Zero Data Retention policy.
This confirms that the tested route rejected an incompatible provider selection.

## Scope

The initial probe disabled reasoning. Sonnet, Gemini, and GLM rejected that setting.
The completed run used the supported `low` effort instead.
These checks establish request acceptance and routing behavior, not independent verification of provider retention practices.
They do not verify tools, image input, streaming, or external Mem0 and voice services.
See [OpenRouter's ZDR policy](https://openrouter.ai/docs/guides/features/zdr) for retention scope and in-memory caching rules.
