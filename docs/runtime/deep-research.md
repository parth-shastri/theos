# Explicit deep research

Deep research starts only from the browser's **Deep research** selection or an explicit user command.
Use `/research QUESTION`, `Deep research: QUESTION`, or `Do deep research on QUESTION`.
Mentioning deep research in a question does not enable it. The model cannot enable the mode itself.
The browser selection applies to one message. The next message defaults to Normal.

Normal questions still receive focused delegate briefs and protected final response capacity.
They do not create research records or receive the deep research tools.

## Research records

The lead researcher and its delegates save records in the existing SQLite database.
Docker stores that database at `/data/theos.sqlite3` on the persistent data volume.
Records belong to one account and conversation. A conversation reset retains saved research.

Select **Research** above the browser conversation to inspect saved runs.
Each run shows its task, status, report, sources, notes, original transcript, and summary checkpoints.
The view shows full saved reports and source text. It does not cut generated text.
Records remain available after a restart and through `list_research` and `read_research` during later explicit research.

## Findings and summaries

Before extensive searching, the agent receives instructions to save a plan.
Search results receive stable source IDs. `read_source` saves the extracted original page text through Exa.
Exa requires `AGENT_EXA_KEY`. Extraction can fail or omit inaccessible page content.
A successful extraction means the service returned text, not that every part of the page was accessible.

`save_research_note` records findings, conflicts, plans, and questions with source references and status.
A supported or disputed finding must cite saved source IDs. The service checks account, conversation, and research ownership.
A replacement note points to its predecessor. Both records remain available for inspection.
Source IDs link evidence to claims. They do not prove the claims.

Deep research summaries use a structured response with narrative progress and all protected record IDs.
The summary request includes saved notes, source metadata, original user requirements, and the previous summary.
The runtime rejects a summary that omits or invents protected IDs.
It keeps the previous working summary when replacement fails.
The next research request receives current saved records independently of the narrative summary.
Original source text remains available through `read_research` even after context summaries.

These checks protect references and original records. They do not verify every sentence of a model's summary.
Conflicts, dates, and uncertainty still need review against the saved evidence.

## Delegate briefs

The coordinator sends a task, relevant background, quoted user requirements, and source IDs to each named delegate.
A delegate receives the latest user message and original earlier messages selected by those quoted requirements.
It does not receive the parent's entire unrelated history.
Legacy string assignments remain supported and retain user messages plus the latest evidence batch.
Delegates return full model-written findings and caveats, not just links.
Deep research delegates also save their own transcripts, reports, evidence, and notes.
They cannot create nested delegates or change account data.

Normal delegation and deep research use [context recovery without fixed call allocations](context-recovery.md).
The [call budget map](call-budgets.md) applies only when a caller explicitly enables bounded mode.
Deep research does not add another model-call pool.

## Report files

When a workspace is configured, the lead researcher can compute results and create, inspect, and deliver report files.
This permits a research request to return PDF, DOCX, and supporting files in the same turn.
Delegates retain their read-only tools. Explicit research does not expose personal account tools.
