# Schedule agent tasks

Scheduled tasks run the normal agent loop at a future time.
They can research information, use enabled tools, and deliver results to the creating conversation.
Reminders only deliver saved text.

## Create and manage a task

Ask Theos in Telegram or browser chat:

- “Every weekday at 9 AM, find recent AI news and give me a brief with sources.”
- “Tomorrow at 6 PM, review my logged meals and summarize my protein intake.”
- “List my scheduled tasks.”
- “Pause my morning briefing.”
- “Resume it tomorrow morning.”
- “Cancel my morning briefing.”
- “Show the recent runs of that task.”

The schedule uses your saved timezone unless you specify another timezone.
Recurring schedules use five-field cron expressions.
For recurring tasks, `due` is an exclusive starting point for the first matching cron time.
One-time tasks run at `due`.
Invalid, past, or ambiguous local times fail validation.

| Tool | Purpose |
| --- | --- |
| `schedule_task` | Create a named one-time or recurring agent task |
| `list_scheduled_tasks` | List your schedules and their states |
| `pause_scheduled_task` | Prevent future runs |
| `resume_scheduled_task` | Resume a paused task from a new future time |
| `cancel_scheduled_task` | Cancel future runs while preserving history |
| `list_scheduled_runs` | Inspect execution and delivery status |

Pause or cancellation does not stop an already running turn.
Cancel and recreate a schedule to change its prompt or recurrence.
`AGENT_MAX_SCHEDULED_TASKS` defaults to 50 pending or paused tasks per owner.

## Execution and delivery

The scheduler claims each occurrence in SQLite before starting the model.
Each run uses the creating session's current model, history, preferences, and tool access.
It shares the ordinary concurrency limit, model-call budget, and turn timeout.
Theos must run for tasks to execute.

A busy conversation defers its scheduled task.
A pending approval or a turn at its model-call limit also defers new scheduled work in that conversation.
Resolve the approval or resume the existing turn before another scheduled run.
A conversation reset abandons those paused run records and clears the conversation state.
It does not cancel future schedules.

Telegram receives streamed text, approval controls, and generated files through its normal renderer.
Browser results remain in conversation history and create a notification.
Open the original browser conversation to approve an action or continue a turn.
The scheduler checks current owner access before starting a run.
It pauses schedules for removed or unauthorized users.

Scheduled execution does not grant approval for external actions.
Gmail sending and Zepto payment and checkout actions require the normal approval. Sandbox execution does not require approval.
Approval results resume the saved tool call rather than creating another scheduled occurrence.

## Downtime and uncertain outcomes

After downtime, a due recurring task runs once and advances to its next future cron time.
It does not execute every missed occurrence.
Occurrence IDs prevent the same scheduled time from starting twice.

Failed, interrupted, uncertain, or budget-exhausted runs pause their schedule.
Read the run status and external service state before resuming the schedule.
A failed Telegram delivery does not rerun the model or its tools.
The delivery status becomes `uncertain`, and conversation history retains the generated result.
This implementation does not add a general durable Telegram outbox.

The new tables are `scheduled_tasks` and `scheduled_runs` in migration 005.
Existing reminders and their delivery behavior remain separate.
See [scheduler dispatch](../src/theos/runtime/scheduled.py), [task tools](../src/theos/services/schedules/tools.py), and [acceptance](runtime/acceptance.md).
