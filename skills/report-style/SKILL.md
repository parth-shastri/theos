---
name: report-style
description: Create PDF and editable DOCX reports with Inter typography, dark green headings, numbered sections, beige tables, dashed rules, yellow status badges, and consistent diagrams. Use for new reports, architecture documents, PRDs, RFCs, runbooks, and technical explainers, unless the user requests another style.
---

# Technical report style

This skill turns one Markdown file into a PDF or editable DOCX.
The style follows the report layout supplied by the deployment operator.
Use neutral labels and examples. Do not add a company name, logo, author, or status that the user did not supply.
Preserve an existing document's style when editing, unless the user asks to restyle it.

- **Cover:** a green small-caps eyebrow, a bold title, and a meta line ("Owner …  Updated …") with a yellow status badge. A dashed rule closes the cover.
- **Headings:** numbered `01 Title`, with a grey number and a green title. Subsections are numbered `5.1`, with a grey number and a black title.
- **Tables:** a beige header row and dashed row rules, with a bold first column.
- **Callouts:** beige boxes with a green left bar. A warning uses a yellow bar.
- **Diagrams:** white rounded boxes with black borders. One green filled box marks the subject. Dashed grey boxes are outside the boundary, and orange marks the isolated or noteworthy part. Containers are dashed green, and a black pill gives a one-line caption.
- **Sequence diagrams:** they use the same boxes, with green step badges, dashed green frames, and yellow notes.

## Files

- `scripts/build_doc.py` converts the Markdown to HTML and prints it to PDF with headless Chrome.
- `scripts/build_docx.py` converts the same source to editable Word text, tables, and callouts.
  It renders diagram figures as images to preserve their layout.
- `assets/style.css` and `assets/edges.js` hold the whole visual system. Do not restyle a document page by page. Change these files only when the house style itself changes.
- `assets/example.md` is a small document that uses every feature. Start a new document from a copy of it.
- `references/flow-diagrams.md`: read it before you draw a flow or architecture diagram.
- `references/sequence-diagrams.md`: read it before you write a sequence diagram.

## Workflow

1. **Collect the content first.** Read the source material, such as a codebase, existing docs, or notes. Decide the sections before you write any HTML. Good architecture docs open with a purpose section, a key-terms table, and a short "in brief" list. The diagrams come next.
2. **Write the Markdown.** Start with front matter:

   ```
   ---
   eyebrow: Team · Architecture
   title: Service architecture
   meta: Scope=Service boundary
   badge: Draft
   ---
   ```

   Number the headings in the source (`## 3. Flow`, `### 3.1 One request`). The script restyles the numbers. A paragraph that starts with a bold phrase (`**Dispatch order.** …`) becomes a lead-in.
   For callouts, write `!!! note "Title."` or `!!! warning "Title."` followed by a body indented four spaces.
3. **Draw the diagrams.**
   - Write each flow or architecture diagram as a ` ```flow ` block of HTML. You can also put it in its own file and pull it in with `<!--include: diagram.html-->`.
   - Write sequence diagrams as normal ` ```mermaid ` `sequenceDiagram` blocks, with `%% primary:` and `%% external:` hints.
   - Mermaid flowcharts are not supported on purpose. Automatic layout produces crossing arrows, and hand placement is what makes these diagrams read cleanly.
4. **Build.**

   ```bash
   uv run --with markdown python <skill-dir>/scripts/build_doc.py doc.md --out doc.pdf --html doc.html
   ```

   The script needs Chrome or Chromium. Set `CHROME=/path` if the script does not find it. The script also needs network access, because it loads Inter and DejaVu Sans Mono from jsdelivr.

   For editable DOCX output:

   ```bash
   uv run <skill-dir>/scripts/build_docx.py doc.md --out doc.docx
   ```

   DOCX requires `python-docx`, `markdown`, and `beautifulsoup4`.
   Documents with diagrams also require `playwright` and Chrome or Chromium.
   Install Inter and DejaVu Sans Mono on the render host for consistent Word previews.
   The Word status badge uses native cell shading rather than a rounded HTML pill.
   Keep the original Markdown when both output formats are requested.
5. **Look at every page.** Rasterize the PDF with `pdftoppm -r 70 -png doc.pdf p`, tile the pages into contact sheets, and view them. Then zoom to 150 dpi or more on each diagram. Fix what you see. Common defects:
   - an arrow that seems to leave the wrong box, because it runs behind a row,
   - a label that sits on an arrowhead,
   - a dashed line drawn over a solid one,
   - an identifier wrapped in the middle of a word,
   - a large blank area before a diagram that did not fit on the page.

   Do not hand over a PDF you have not looked at.
   For DOCX, render it through LibreOffice, then inspect every rendered page.
   Check that body text, headings, and tables remain editable.
   Check that the output contains no source brand names or placeholder facts.

## Theos execution

Use `load_skill(name="report-style")` to read these instructions.
Load scripts, CSS, JavaScript, examples, and references through the same tool's `resource` argument.
Copy required files into the remote sandbox with `sandbox_write_file` before execution.
The assistant-host skill path is not a sandbox path.
Check dependencies in the sandbox. Never assume that the host's libraries are installed there.
Render, inspect with `sandbox_view_image`, and deliver through `sandbox_send_file_to_user`.
Sandbox execution does not require approval in Theos.
If dependencies or rendering are unavailable, report the limitation without claiming a verified result.

## Writing the prose

The style is plain and direct, so the text should be too. If the `ste-writing` skill is available, use its STE-flavored mode for the prose:

- short sentences in the active voice,
- one name for each thing,
- no semicolons,
- no marketing words.

Put rules in lists and procedures in numbered steps. Put all identifiers, settings, and paths in backticks.

Use a table for anything that has the shape of a lookup, such as roles, settings, routes, or migrations. A table reads faster than a paragraph and prints well in this style.

When a diagram is too dense to label every arrow, draw the structure. Then add a "From / To / What flows" table after the diagram, so the document keeps every connection.

## Color meaning

Color carries meaning, so keep it consistent across a document:

| Color | Meaning |
| --- | --- |
| Green fill (`#186752`) | The subject or entry point. Use one or two per diagram. |
| Orange (`#f2672c`) | Isolated, sandboxed, mocked, or needs attention. |
| Dashed grey | Outside the system boundary. |
| Yellow (`#efcc3a`) | The status badge, notes, and warnings. |
| Beige (`#f1f2ed`) | Table headers, code, callouts, and container fills. |
