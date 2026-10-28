"""Check React composer prompts and recorder feedback without microphone capture."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_composer_prompts_and_voice_feedback_preserve_drafts():
    recorder = Path("web/src/hooks/useRecorder.js").read_text()
    recorder = recorder[recorder.index("export function useRecorder") :].replace(
        "export function", "function"
    )
    prompt = Path("web/src/hooks/useComposerPrompt.js").read_text()
    prompt = prompt[prompt.index("export function composerPlaceholder") :].replace(
        "export function", "function"
    )
    script = r"""
import assert from 'node:assert/strict';
import {composerPrompts, mobileComposerPrompts} from './web/src/state/config.js';
const slots = [], effects = [];
let cursor = 0, dirty = false;
function useState(initial) {
  const index = cursor++;
  if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
  return [slots[index], value => {
    const next = typeof value === 'function' ? value(slots[index]) : value;
    if (!Object.is(slots[index], next)) { slots[index] = next; dirty = true; }
  }];
}
function useRef(initial) {
  const index = cursor++;
  return slots[index] ||= {current: initial};
}
function useEffect(callback, dependencies) {
  const index = cursor++, previous = slots[index];
  if (!previous || dependencies.some((value, i) => !Object.is(value, previous.dependencies[i]))) {
    effects.push(() => { previous?.cleanup?.(); slots[index] = {dependencies, cleanup: callback()}; });
  }
}
const intervals = new Map(), handlers = new Map();
let nextInterval = 0, stopped = 0, busy = false, draft = '', focused = false, mobile = false, active = true, statusText = '';
const setInterval = callback => { intervals.set(++nextInterval, callback); return nextInterval; };
const clearInterval = id => intervals.delete(id);
const window = {isSecureContext: true,
  addEventListener(type, callback) { if (!handlers.has(type)) handlers.set(type, new Set()); handlers.get(type).add(callback); },
  removeEventListener(type, callback) { handlers.get(type)?.delete(callback); },
};
const document = {hidden: false, body: {classList: {toggle() {}, remove() {}}},
  getElementById() { return {style: {removeProperty() {}}}; },
};
const matchMedia = () => ({matches: false});
const navigator = {mediaDevices: {async getUserMedia() { return {getTracks: () => [{stop() { stopped++; }}]}; }}};
let pendingStop, transcriptResult, requestStarted;
class MediaRecorder {
  static isTypeSupported() { return true; }
  constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive'; this.ondataavailable({data: new Blob(['test audio'])});
    pendingStop = Promise.resolve().then(() => this.onstop());
  }
}
const me = {voice: {transcription: true, max_upload_bytes: 1024}};
const useWorkspace = () => ({me, busy,
  setWorking(value) { busy = value; dirty = true; },
  async json(path) {
    if (path === '/api/files') return {id: 'test-file'};
    requestStarted(); return await transcriptResult;
  },
  showError(error) { if (error.name !== 'AbortError') statusText = error.message; },
  status(text) { statusText = text; },
});
"""
    script += recorder + prompt
    script += r"""
let voice, placeholder;
function render() {
  do {
    dirty = false; cursor = 0;
    voice = useRecorder(text => { draft = appendTranscript(draft, text); focused = true; });
    placeholder = useComposerPrompt({active, draft, focused, mobile, activity: voice.activity});
    while (effects.length) effects.shift()();
  } while (dirty);
}
function rotate() { for (const callback of intervals.values()) callback(); render(); }
async function transcribe(previous, text, failure = false) {
  draft = previous; focused = false; render();
  await voice.toggle(); render();
  assert.equal(placeholder, 'Listening...');
  assert.equal(draft, previous);
  let complete, reject;
  transcriptResult = new Promise((resolve, fail) => { complete = resolve; reject = fail; });
  const started = new Promise(resolve => { requestStarted = resolve; });
  await voice.toggle(); await started; render();
  assert.equal(placeholder, 'Transcribing...');
  assert.equal(voice.activity, 'Transcribing...');
  rotate(); assert.equal(placeholder, 'Transcribing...');
  if (failure) reject(new Error('Transcription failed. Try again.'));
  else complete({text});
  await pendingStop; render();
  assert.equal(busy, false);
  assert.equal(voice.activity, '');
  assert.equal(statusText, failure ? 'Transcription failed. Try again.' : '');
  assert.equal(draft, failure ? previous : [previous, text].filter(Boolean).join('\n'));
}
render();
for (let i = 0; i < 2; i++) for (const callback of handlers.get('pageshow')) callback({persisted: true});
assert.equal(intervals.size, 1, 'Restoring a page must not duplicate the prompt timer');
assert.equal(placeholder, 'Make me a billionaire...');
rotate(); assert.equal(placeholder, 'Initiate a worldwide peacekeeping mission...');
mobile = true; render(); assert.equal(placeholder, 'Tax my soul');
for (let i = 0; i < mobileComposerPrompts.length; i++) { rotate(); assert.equal(placeholder.split(/\s+/).length, 3); }
focused = true; mobile = false; render(); rotate(); assert.equal(placeholder, 'Start Typing...');
draft = 'Keep this draft'; focused = false; render(); rotate(); assert.equal(draft, 'Keep this draft');
draft = ''; document.hidden = true; render(); const paused = placeholder; rotate(); assert.equal(placeholder, paused);
document.hidden = false; active = false; render(); rotate(); assert.equal(placeholder, paused);
active = true; render(); for (let i = 0; i < composerPrompts.length; i++) rotate(); assert.equal(placeholder, paused);
await transcribe('', 'Hello from the transcript'); assert.equal(placeholder, 'Start Typing...');
await transcribe('Existing draft', 'Append this transcript');
await transcribe('Keep on failure', '', true);
await voice.toggle(); render(); voice.cancel(); await pendingStop; render();
assert.equal(draft, 'Keep on failure'); assert.equal(statusText, ''); assert.equal(voice.activity, ''); assert.equal(busy, false);
assert.ok(stopped >= 4, 'Every recording must release its stream');
for (const slot of slots.toReversed()) slot?.cleanup?.();
assert.equal(intervals.size, 0, 'Unmount must release the idle prompt timer');
"""
    result = subprocess.run(
        ["node", "--input-type=module"], input=script, text=True, capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
