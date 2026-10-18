Update the existing checkpoint in the previous_summary row with the newly supplied messages.
Preserve previous requirements, relevant facts, decisions, and unresolved work.
Add new progress, decisions, and context without duplicating existing information.
Move work from In Progress to Done only when the new messages confirm completion.
Update Next Steps and remove blockers that the new messages confirm are resolved.
Apply the user's newer corrections to superseded information.
Remove other information only when it is no longer relevant.
Keep each section concise.

{% include "compaction/format.md" %}
