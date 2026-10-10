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
- Start normal changes on a topic branch from `dev`, including fixes, features, chores, and documentation.
- For an urgent Pi release fix, start a `fix/<name>` branch from `rpi`. Merge it into `rpi` through a PR.
- After a Pi hotfix, cherry-pick the fix onto a separate topic branch from `dev` and merge through a PR.
- Never use the `codex/` branch prefix. Use `fix/`, `feature/`, `chore/`, or `docs/` as appropriate.
- Merge normal topic branches into `dev` through a PR.
- When a destination is ready, promote `dev` to `main` or `rpi` through a PR. Each destination needs its own PR.
- Promotions are independent. Do not require both promotion PRs for every change. Publish Pi releases from `rpi`.
- Do not commit changes directly to `dev`, `main`, or `rpi`.
- Preserve source attribution and the starter provenance manifest.
- Follow `/Users/nightowl/WRITING.md` for long Markdown changes when that file exists.
- Do not claim that a planned component is implemented.
