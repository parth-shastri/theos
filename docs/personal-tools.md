# Personal tools

For tasks that run the model and tools at a future time, read [scheduled tasks](scheduled-tasks.md).

Personal tools store records under the authenticated owner in SQLite.
They work without external memory or Google accounts.
A conversation reset retains these records.
The [tool catalog](tool-catalog.md) lists exact callable names and dependencies.

## Preferences

Ask the assistant to set your timezone, calorie goal, display name, or instruction preference.
The default calorie goal is 2000.
A saved goal must range from 100 to 20000.
The default timezone comes from `AGENT_TIMEZONE`.

`display_name` identifies the user.
`AGENT_NAME` identifies the assistant.
Set the instruction preference to an empty string to remove its override.
Preferences cannot grant application permissions.

## Reminders

Example requests:

- “Remind me tomorrow at 09:00 Asia/Kolkata to review my notes.”
- “List my reminders.”
- “Cancel this reminder.”

A reminder belongs to the conversation that created it.
The scheduler saves each occurrence before delivery.
Recurring reminders use five-field cron expressions in the selected timezone.
Ambiguous local times need an explicit UTC offset.
UTC means Coordinated Universal Time.

After downtime, a recurring reminder advances from the current time.
It does not send every missed occurrence.
Browser reminders appear in the notification view.
Telegram reminders return to the saved chat and topic.
Uncertain delivery remains available for operator review.

## Meals

Meal tools save descriptions, calories, nutrients, and meal times.
Daily summaries use the user timezone.
The assistant can edit or delete a selected meal.

A connected Google Health account also queues nutrition exports.
A local save can succeed while its remote export remains pending.
Do not save the same meal again to retry an export.
See [Google Health](google-health.md).

## Training

Training tools support rotating programs and seven-day weekly programs.
A program can include resistance work, cardio, recovery, mobility, and rest.
Saved program versions preserve the meaning of older workout records.

Use the tools to read the current prescription, log results, advance the cycle, and inspect comparable sessions.
Workout records can include individual sets, duration, distance, and completion status.
Training metrics need explicit units and measurement times.
Deleting a workout does not require deleting the program.

## Private tables

Each owner receives a separate SQLite database for custom tables.
The assistant can create tables and named query templates.
Templates accept one SELECT, INSERT, UPDATE, or DELETE statement with bound parameters.
The database authorizer restricts unsafe operations and extension access.

Deleting a table requires approval.
Review that action because it removes the table and its rows.
Queries cannot select another owner through tool arguments.

## Research and skills

Search uses Exa, with Brave as a configured fallback.
Weather uses Open-Meteo.
Installed skills supply instructions and bounded text resources.
They do not grant permissions or install executable tools automatically.

`delegate_tasks` can run up to three research tasks with the parent model-call budget.
Delegates receive search, weather, and skill tools only.
They cannot change personal records or create further delegates.
