# Task

Summarize the beginning of the supplied turn, including its original user request and the progress already made.
Later messages remain separately available after this checkpoint.

# Instructions

- Preserve confirmed findings, decisions, unresolved work, and context needed to understand those later messages.
- Do not infer or reconstruct later messages. Keep the summary concise.

# Output Format

Use these Markdown headings:

```markdown
## Original Request
[What the user asked for, including requirements and corrections]

## Progress So Far
- [Confirmed work and findings from the supplied messages]

## Context Needed to Continue
- [Facts, references, and unresolved work needed to resume]
```
