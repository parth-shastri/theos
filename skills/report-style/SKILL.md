---
name: report-style
description: Construct a requested report from supplied requirements and evidence. New reports use the preinstalled report style unless the user requests another style or format.
---

# Create a report

Use the user's requested scope, audience, date range, sections, and output format.
Use supplied evidence. Do not invent facts, values, or sources.
Ask one short question only when missing information blocks an accurate report.

New reports default to PDF with the preinstalled style.
Preserve an existing document's style when editing.
Follow any explicit style or format request.

## Content and visuals

Write for the user's decision or understanding. Lead with the answer, key findings, and their implications.
Structure the report around the subject, rather than the steps the agent performed.
Use evidence-based charts for trends, comparisons, and distributions. Use diagrams for relationships, flows, and choices.
Choose useful visuals automatically. The user does not need to ask for charts or diagrams.
Choose visuals that answer the user's question. Add clear labels, units, periods, and a short explanation of each takeaway.
Keep currencies separate unless the task requires a supported conversion. Never invent data for a chart.
Include useful next steps, concise material limitations, and source references where they support the findings.
Keep tool logs, read counts, generation details, and provenance tables out of the main report unless requested.

## Build and deliver

For flow or sequence diagrams, load the relevant guide under `references/` with `load_skill`.
Ensure each selected output format contains the visuals, rather than silently omitting them during conversion.
Write the report as Markdown at `/workspace/report.md`.
The report style files and builders are preinstalled at `/opt/theos/report-style`.
Do not copy those files or install report dependencies.

Run `theos-report /workspace/report.md` to create `/workspace/report.pdf`.
Use `--format docx` only when the user requests an editable Word file.
Deliver the requested output with `send_file_to_user`.
