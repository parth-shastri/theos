## Tool Execution Batches

- Request at most {{ batch_size }} tool calls per response. Wait for results before requesting the next group.
- A not_started result means no tool executed. Correct the problem and submit a new call with a new ID.
- A failed result means the tool ran and failed. An unknown result means the action may have happened.
- Never repeat completed or unknown actions merely because a batch was split.
{% if previous_count > batch_size %}
### Previous Batch

Your last response requested {{ previous_count }} calls, above the recommended {{ batch_size }}.
They were processed in bounded batches with their original IDs and approval checks.
Read each result and keep future responses within {{ batch_size }} calls. Do not resubmit this batch.
{% endif %}
