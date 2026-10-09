# Theos agent instructions

Read [MEMORY.md](MEMORY.md) before changing the architecture or implementation plan.
Read [docs/code-structure.md](docs/code-structure.md) for service boundaries and [acceptance](docs/runtime/acceptance.md) for open checks.

- Theos owns the copied harness under `src/harness`.
- Use `gpt-6-luna` through OpenAI Responses as the default model.
- Telegram is the first transport.
- Follow the uploaded Agent Harness framework preserved under `docs/architecture/reference`.
- Use the Excalidraw MCP for architecture diagram edits and keep local artifacts in sync.
- Use Excalidraw's traditional handwriting font, font family `1`.
- Document concrete tools and dependencies in `docs/tool-catalog.md`.
- Keep the reference assistant's name and repository URL out of project artifacts and responses.
- Keep generic harness behavior separate from assistant services and transport code.
- Record new project decisions in `MEMORY.md`.
- Preserve source attribution and the starter provenance manifest.
- Follow `/Users/nightowl/WRITING.md` for long Markdown changes when that file exists.
- Do not claim that a planned component is implemented.
