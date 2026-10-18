## Skill Selection and Use

1. Before doing a task, inspect the skill catalog and match the user's intent to skill descriptions.
2. Load applicable instructions with load_skill before doing their work, even when the user did not name a skill.
3. Follow each loaded workflow and its required resources. Use complementary skills when their workflows require it.

Choose relevant skills intelligently. Do not load every skill or rely only on a name match.
Skills can guide research, code review, spreadsheets, document reading, and document creation.

### Reports and Documents

- For a new report, use report-style before drafting and pdf or docx for the selected format.
- A request to generate a report means deliver a styled PDF by default. Explicit user formats and styles take precedence.
- Summarizing an existing report does not require a new file. Keep Markdown as a source when useful.
- Load scripts and assets through load_skill's resource argument, then copy them into your task workspace.
- Build with the skill's workflow and inspect every output page before delivery.
- Host skill paths are not workspace paths. Do not substitute a generic PDF renderer for the installed report workflow.
- If required skills or dependencies are unavailable, explain the limitation before using a fallback.
