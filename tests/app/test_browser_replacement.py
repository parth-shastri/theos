"""Exercise the React conversation reducer and streamed event reader."""

import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_browser_replacement_handles_streaming_and_completed_drafts():
    script = r"""
import assert from 'node:assert/strict';
import {chatReducer, initialChat, readEvents} from './web/src/state/chat.js';
const reduce = (state, action) => chatReducer(state, {...action, now: 1000});
async function run(events) {
  let state = reduce(initialChat, {type: 'LOAD', session: {...initialChat, id: 'session', history: []}});
  state = reduce(state, {type: 'START', sessionId: 'session'});
  const bytes = new TextEncoder().encode(events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join(''));
  const response = new Response(new ReadableStream({start(controller) {
    for (let offset = 0; offset < bytes.length; offset += 19) controller.enqueue(bytes.slice(offset, offset + 19));
    controller.close();
  }}));
  let error;
  try {
    await readEvents(response, event => {
      const before = JSON.stringify(state);
      const previous = state;
      state = reduce(state, {type: 'EVENTS', sessionId: 'session', events: [event]});
      assert.equal(JSON.stringify(previous), before, 'Reducers must not mutate prior React state');
    });
  } catch (value) { error = value; }
  state = reduce(state, {type: 'FINISH', sessionId: 'session'});
  return {state, error};
}
const final = 'Full source evidence. '.repeat(2000) + 'FINAL URL';
const cases = [
  [{type: 'text', text: 'Interrupted draft'}],
  [{type: 'assistant_complete', text: 'Completed draft'}],
  [{type: 'assistant_complete', text: 'Earlier draft'},
   {type: 'assistant_complete', text: 'Later draft'},
   {type: 'thinking'}, {type: 'text', text: 'Interrupted third draft'}],
];
for (const draft of cases) {
  const {state, error} = await run([...draft, {type: 'answer_replace', text: final}, {type: 'done', status: 'partial'}]);
  assert.equal(error, undefined);
  assert.deepEqual(state.entries.filter(row => row.kind === 'message').map(row => row.text), [final]);
  assert.equal(state.busy, false);
}
const {state} = await run([
  {type: 'compaction', status: 'started', compaction_id: 'one', parent_call_id: 'delegate'},
  {type: 'compaction', status: 'progress', compaction_id: 'one', parent_call_id: 'delegate'},
  {type: 'compaction', status: 'started', compaction_id: 'two', parent_call_id: 'delegate'},
  {type: 'compaction', status: 'completed', compaction_id: 'one', parent_call_id: 'delegate'},
  {type: 'done', status: 'interrupted'},
]);
const rows = state.entries.filter(row => row.kind === 'compaction');
assert.equal(rows.length, 2);
assert.equal(rows[0].text, 'Context ready. Continuing.');
assert.match(rows[1].text, /stopped/);
assert.ok(rows.every(row => !row.active));
const interrupted = await run([{type: 'compaction', status: 'started', compaction_id: 'disconnected'}]);
assert.match(interrupted.error.message, /connection ended/);
assert.match(interrupted.state.entries.find(row => row.kind === 'compaction').text, /stopped/);
assert.ok(interrupted.state.entries.every(row => !row.thinking && !row.streaming));
const approval = {id: 'approval', call_id: 'call', tool: 'preview_action'};
let reviewed = reduce(initialChat, {type: 'LOAD', session: {...initialChat, id: 'session', history: [], approvals: [approval]}});
reviewed = reduce(reviewed, {type: 'START', sessionId: 'session'});
assert.equal(reviewed.approvals.length, 1, 'Keep approvals until the server accepts the decision');
reviewed = reduce(reviewed, {type: 'APPROVAL_ACCEPTED', sessionId: 'session', item: approval, approved: true});
assert.deepEqual(reviewed.approvals, []);
reviewed = reduce(reviewed, {type: 'EVENTS', sessionId: 'session', events: [{type: 'tool', call_id: 'call', name: 'preview_action', status: 'completed', content: 'Done'}]});
assert.equal(reviewed.entries.filter(row => row.kind === 'tool').length, 1);
assert.equal(reviewed.entries.find(row => row.kind === 'tool').status, 'completed');
assert.strictEqual(reduce(reviewed, {type: 'EVENTS', sessionId: 'other', events: [{type: 'title', title: 'Stale'}]}), reviewed);

"""
    result = subprocess.run(
        ["node", "--input-type=module"], input=script, text=True, capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
