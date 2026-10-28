"""Check microphone visual feedback and cleanup without capturing audio."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_voice_meter_drives_both_surfaces_and_releases_audio_resources():
    source = Path("web/src/hooks/useRecorder.js").read_text()
    meter = source[source.index("  const stopMeter =") : source.index("  const release =")]
    meter += source[source.index("  const startMeter =") : source.index("  useEffect(")]
    script = r"""
const assert = require('node:assert/strict');
const scope = {
  observe: observer => observer,
  onDispose() {},
  listen: (target, ...args) => target?.addEventListener?.(...args),
  setTimeout: (...args) => setTimeout(...args),
  clearTimeout: id => clearTimeout(id),
  setInterval: (...args) => setInterval(...args),
  clearInterval: id => clearInterval(id),
  requestAnimationFrame: callback => requestAnimationFrame(callback),
  cancelAnimationFrame: id => cancelAnimationFrame(id),
};
const state = {current: {}};
let amplitude = 0.12, contexts = 0, closed = 0, disconnected = 0;
let nextFrame = 0;
const frames = new Map(), cancelled = [];
const styles = new Map(['composer', 'voice-ambience'].map(id => [id, new Map()]));
const $ = id => ({style: {
  setProperty(key, value) { styles.get(id).set(key, value); },
  removeProperty(key) { styles.get(id).delete(key); },
}});
const document = {getElementById: $};
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
  await startMeter({});
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
  stopMeter();
  assert.equal(state.current.meter, null);
  assert.equal(frames.size, 0);
  assert.ok(cancelled.length);
  assert.equal(disconnected, 2);
  assert.equal(closed, 1);
  for (const style of styles.values()) assert.ok(!style.has('--voice-level'));
  motion.matches = true;
  await startMeter({});
  assert.equal(contexts, 1, 'Reduced motion must retain static feedback');
  motion.matches = false;
  await startMeter({});
  motion.matches = true;
  state.current.meter.changed();
  assert.equal(state.current.meter, null);
  assert.equal(closed, 2);
  for (const style of styles.values()) assert.ok(!style.has('--voice-level'));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
