"""Check composer prompts and transcription feedback without microphone capture."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_composer_prompts_and_voice_feedback_preserve_drafts():
    source = Path("src/theos/transports/browser/static/app.js").read_text()
    prompts = source[
        source.index("const composerPrompts =") : source.index("function stopRecordingMeter()")
    ]
    recording = source[
        source.index("function releaseRecording()") : source.index(
            'window.addEventListener("pagehide"'
        )
    ]
    script = r"""
const assert = require('node:assert/strict');
function element() {
  return {value: '', textContent: '', className: '', hidden: false, disabled: false,
    attributes: new Map(),
    setAttribute(key, value) { this.attributes.set(key, value); },
    removeAttribute(key) { this.attributes.delete(key); },
    focus() { document.activeElement = this; syncComposerPlaceholder(); },
    get classList() {
      const owner = this;
      return {
        contains(value) { return owner.className.split(' ').includes(value); },
        toggle(value, enabled) {
          const classes = new Set(owner.className.split(' ').filter(Boolean));
          enabled ? classes.add(value) : classes.delete(value);
          owner.className = [...classes].join(' ');
        },
        add(value) { this.toggle(value, true); },
        remove(value) { this.toggle(value, false); },
      };
    },
  };
}
const ids = new Map(['message', 'status', 'composer', 'workspace', 'microphone',
  'cancel-recording'].map(id => [id, element()]));
const $ = id => ids.get(id);
const document = {activeElement: null, hidden: false, body: element()};
const promptMedia = {matches: false, addEventListener(_, callback) { this.change = callback; }};
const matchMedia = () => promptMedia;
const intervals = new Map();
let intervalId = 0;
const setInterval = callback => { intervals.set(++intervalId, callback); return intervalId; };
const clearInterval = id => intervals.delete(id);
let busy = false, recorder = null, recordingStream = null, recordingTimer;
let recordingCancelled = false, stopped = 0, pendingStop;
const me = {voice: {max_upload_bytes: 1024}};
const navigator = {mediaDevices: {async getUserMedia() {
  return {getTracks: () => [{stop() { stopped++; }}]};
}}};
class MediaRecorder {
  static isTypeSupported() { return true; }
  constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    this.ondataavailable({data: new Blob(['test audio'])});
    pendingStop = Promise.resolve().then(() => this.onstop());
  }
}
function setBusy(value) { busy = value; }
function setIconButton() {}
function stopRecordingMeter() {}
function startRecordingMeter() {}
function resizeComposer() { syncComposerPlaceholder(); }
function showError(error) { $('status').textContent = error.message; $('status').className = 'error'; }
let transcriptResult, requestStarted;
async function json(path) {
  if (path === '/api/files') return {id: 'test-file'};
  requestStarted();
  return await transcriptResult;
}
async function transcribe(draft, text, failure = false) {
  $('message').value = draft;
  document.activeElement = null;
  await $('microphone').onclick();
  assert.equal($('message').placeholder, 'Listening...');
  assert.equal($('message').value, draft);
  let complete, reject;
  transcriptResult = new Promise((resolve, fail) => { complete = resolve; reject = fail; });
  const started = new Promise(resolve => { requestStarted = resolve; });
  await $('microphone').onclick();
  await started;
  assert.equal($('message').placeholder, 'Transcribing...');
  assert.equal($('message').attributes.get('aria-busy'), 'true');
  assert.equal($('status').classList.contains('placeholder-status'), !draft);
  rotateComposerPrompt();
  assert.equal($('message').placeholder, 'Transcribing...');
  if (failure) reject(new Error('Transcription failed. Try again.'));
  else complete({text});
  await pendingStop;
  assert.equal(busy, false);
  assert.equal($('message').attributes.has('aria-busy'), false);
  assert.equal($('status').textContent, failure ? 'Transcription failed. Try again.' : '');
  assert.equal($('message').value, failure ? draft : [draft, text].filter(Boolean).join('\n'));
}
"""
    script += prompts + recording
    script += r"""
(async () => {
  startComposerPrompts();
  startComposerPrompts();
  assert.equal(intervals.size, 1, 'Restoring a page must not duplicate the prompt timer');
  assert.equal($('message').placeholder, 'Make me a billionaire...');
  rotateComposerPrompt();
  assert.equal($('message').placeholder, 'Initiate a worldwide peacekeeping mission...');
  promptMedia.matches = true;
  promptMedia.change();
  assert.equal($('message').placeholder, 'Tax my soul');
  for (let i = 0; i < mobileComposerPrompts.length; i++) {
    rotateComposerPrompt();
    assert.equal($('message').placeholder.split(/\s+/).length, 3);
  }
  $('message').focus();
  promptMedia.matches = false;
  promptMedia.change();
  rotateComposerPrompt();
  assert.equal($('message').placeholder, 'Start Typing...');
  $('message').value = 'Keep this draft';
  document.activeElement = null;
  rotateComposerPrompt();
  assert.equal($('message').value, 'Keep this draft');
  $('message').value = '';
  document.hidden = true;
  rotateComposerPrompt();
  assert.equal(composerPromptIndex, 1);
  document.hidden = false;
  $('workspace').hidden = true;
  rotateComposerPrompt();
  assert.equal(composerPromptIndex, 1);
  $('workspace').hidden = false;
  for (let i = 0; i < composerPrompts.length; i++) rotateComposerPrompt();
  assert.equal(composerPromptIndex, 1, 'Idle prompts wrap around');
  await transcribe('', 'Hello from the transcript');
  assert.equal($('message').placeholder, 'Start Typing...');
  await transcribe('Existing draft', 'Append this transcript');
  await transcribe('Keep on failure', '', true);
  await $('microphone').onclick();
  $('cancel-recording').onclick();
  await pendingStop;
  assert.equal($('message').value, 'Keep on failure');
  assert.equal($('status').textContent, '');
  assert.equal(composerVoiceActivity, '');
  assert.equal(busy, false);
  assert.ok(stopped >= 4, 'Every recording must release its stream');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
