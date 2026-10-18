"""Check microphone visual feedback and cleanup without capturing audio."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_voice_meter_drives_both_surfaces_and_releases_audio_resources():
    source = Path("src/theos/transports/browser/static/app.js").read_text()
    meter = source[
        source.index("function stopRecordingMeter()") : source.index("function releaseRecording()")
    ]
    script = r"""
const assert = require('node:assert/strict');
let recordingMeter = null, amplitude = 0.12, contexts = 0, closed = 0, disconnected = 0;
let nextFrame = 0;
const frames = new Map(), cancelled = [];
const styles = new Map(['composer', 'voice-ambience'].map(id => [id, new Map()]));
const $ = id => ({style: {
  setProperty(key, value) { styles.get(id).set(key, value); },
  removeProperty(key) { styles.get(id).delete(key); },
}});
const motion = {matches: false, addEventListener() {}, removeEventListener() {}};
const matchMedia = () => motion;
const requestAnimationFrame = callback => { frames.set(++nextFrame, callback); return nextFrame; };
const cancelAnimationFrame = id => { cancelled.push(id); frames.delete(id); };
const window = {AudioContext: class {
  constructor() { contexts++; }
  async resume() {}
  createMediaStreamSource() { return {connect() {}, disconnect() { disconnected++; }}; }
  createAnalyser() { return {
    fftSize: 1024,
    getFloatTimeDomainData(samples) { samples.fill(amplitude); },
    disconnect() { disconnected++; },
  }; }
  async close() { closed++; }
}};
function frame() {
  const [id, callback] = frames.entries().next().value;
  frames.delete(id);
  callback();
}
"""
    script += meter
    script += r"""
(async () => {
  await startRecordingMeter({});
  const first = Number(styles.get('composer').get('--voice-level'));
  assert.ok(first > 0 && first < 1);
  assert.equal(styles.get('voice-ambience').get('--voice-level'), String(first));
  amplitude = 0.2;
  frame();
  const louder = Number(styles.get('voice-ambience').get('--voice-level'));
  assert.ok(louder > first, 'Both the wave field and composer must respond to louder input');
  amplitude = 0;
  for (let i = 0; i < 12; i++) frame();
  assert.ok(Number(styles.get('voice-ambience').get('--voice-level')) < louder);
  stopRecordingMeter();
  assert.equal(recordingMeter, null);
  assert.equal(frames.size, 0);
  assert.ok(cancelled.length);
  assert.equal(disconnected, 2);
  assert.equal(closed, 1);
  for (const style of styles.values()) assert.ok(!style.has('--voice-level'));
  motion.matches = true;
  await startRecordingMeter({});
  assert.equal(contexts, 1, 'Reduced motion must retain static feedback');
  motion.matches = false;
  await startRecordingMeter({});
  motion.matches = true;
  recordingMeter.onMotionChange();
  assert.equal(recordingMeter, null);
  assert.equal(closed, 2);
  for (const style of styles.values()) assert.ok(!style.has('--voice-level'));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
