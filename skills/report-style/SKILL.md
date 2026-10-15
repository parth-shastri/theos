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

Write the report as Markdown at `/workspace/report.md`.
The report style files and builders are preinstalled at `/opt/theos/report-style`.
Do not copy those files or install report dependencies.

Run `theos-report /workspace/report.md` to create `/workspace/report.pdf`.
Use `--format docx` only when the user requests an editable Word file.
Deliver the requested output with `send_file_to_user`.
