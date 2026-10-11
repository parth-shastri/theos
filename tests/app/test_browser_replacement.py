"""Run the browser stream handler against a small in-memory display."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_browser_replacement_handles_streaming_and_completed_drafts():
    source = Path("src/theos/transports/browser/static/app.js").read_text()
    handler = source[
        source.index("async function stream(") : source.index("async function newSession(")
    ]
    script = r"""
const assert = require('node:assert/strict');
let selected = 'session', rows = [], input = [];
const me = {id: 'alice'}, speechControls = new Set();
const status = {classList: {remove() {}}, querySelectorAll() {return [];}};
const $ = () => status;
function bubble() {
  const row = {visible: true, remove() {this.visible = false;}, querySelector() {return null;}};
  const body = {parentElement: row, textContent: ''};
  row.body = body;
  rows.push(row);
  return body;
}
const TheosMarkdown = {render(body, text) {body.textContent = text;}};
const streamingMetadata = () => ({start() {}, update() {}, finish() {}});
const setBusy = () => {}, thinking = () => {}, scrollChat = () => {};
const finishThinking = () => {}, speechControl = () => null;
const toolActivity = () => {}, addFileLink = () => {}, approvals = () => {};
const listSessions = async () => {}, refreshCosts = async () => {};
const json = async () => ({status: 'partial', approvals: [], title: 'Research'});
const sessionStorage = {getItem() {return null;}};
const showError = error => {throw error;};
const api = async () => {
  const data = new TextEncoder().encode(input.map(e => 'data: ' + JSON.stringify(e) + '\n\n').join(''));
  let sent = false;
  return {body: {getReader() {return {async read() {
    if (sent) return {done: true};
    sent = true;
    return {value: data, done: false};
  }}}}};
};
"""
    script += handler
    script += r"""
(async () => {
  const final = 'Full source evidence. '.repeat(2000) + 'FINAL URL';
  const cases = [
    [{type: 'text', text: 'Interrupted draft'}],
    [{type: 'assistant_complete', text: 'Completed draft'}],
    [{type: 'assistant_complete', text: 'Earlier draft'},
     {type: 'assistant_complete', text: 'Later draft'},
     {type: 'thinking'}, {type: 'text', text: 'Interrupted third draft'}],
  ];
  for (const draft of cases) {
    rows = [];
    input = [...draft, {type: 'answer_replace', text: final}, {type: 'done', status: 'partial'}];
    await stream('/turn', {text: 'Research'});
    assert.deepEqual(rows.filter(row => row.visible).map(row => row.body.textContent), [final]);
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
