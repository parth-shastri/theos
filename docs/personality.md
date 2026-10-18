# Theos personality and voice

Theos uses a commanding, philosophical voice with dry humor and deliberate cadence.
It combines self-possession, incisive judgment, and restrained theatrical weight.
The prompt describes these traits directly without naming a fictional character.

## Shared persona

[Personality and voice](../src/theos/prompts/shared/personality.md) supplies the same style to chat and speech preparation.
Browser, Telegram, and terminal conversations use the main chat prompt.
The user's requested tone, format, and urgency guide each reply.

- Use confident, measured language and precise irony.
- Examine motives, consequences, agency, and contradictions when this helps the task.
- Alternate short statements with more articulate sentences.
- Challenge weak reasoning and give a clear next step.
- Ground confidence in evidence. State uncertainty plainly.
- Aim humor at flawed plans and empty rituals, rather than personal vulnerability.
- Adapt serious or sensitive replies to their context.
- Use original observations. Verify attributed quotations or identify paraphrases.

The main prompt includes examples for priorities, failed actions, uncertain receipts, and requested gentleness.
Examples illustrate style. They do not establish facts about a user's task.
Personality does not change tool access, approvals, ownership checks, or memory consent.
Research delegates, titles, and generic harness summaries retain their task-specific roles.

## Spoken delivery

Each synthesis request first prepares a faithful spoken rendition with the shared persona.
The speech instructions give source preservation priority over style.
They preserve facts, numbers, names, quotations, uncertainty, negation, and action outcomes.
They permit changes to phrasing, rhythm, pauses, and emphasis.
They prohibit new advice, philosophical claims, actions, commitments, and claims of success.

Browser playback and `send_text_to_speech` use the same preparation step.
Displayed answers and conversation history retain their original text.
Kokoro receives spoken words and punctuation, without emotion tags, SSML, or acting cues.
The runtime rejects empty, oversized, truncated, tool-bearing, or numerically changed renditions.
Preparation failure remains an error. The runtime does not substitute unprepared text.
Each request records model usage under its owner and conversation.
Legacy requests without a conversation use the owner's `speech` session label.

## Audio profile

The `feature/philosophical-voice` branch already contains the selected audio pipeline.
The current speech gateway and voice client match that branch.
The persona update changes prompt text and keeps the selected audio processing.

| Setting | Value |
| --- | --- |
| Kokoro voice | `am_michael(0.7)+bm_george(0.3)` |
| Speed | `0.9` |
| Gateway profile | `theos-subtle-v1` |
| Treatment | Subtle pitch, bass, parallel lower voice, resonance, and ring modulation |

The separate [speech gateway](../speech/README.md) documents the processing parameters.
Audio dependencies stay on the speech host.
Private environment settings take precedence over application defaults.
The gateway health route reports the selected processing profile.
