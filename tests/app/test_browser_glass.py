"""Check glass refresh cleanup and mouse versus touch feedback."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_glass_refresh_releases_removed_panes_and_keeps_press_feedback_for_touch():
    source = Path("web/src/runtime/glass.js").read_text().replace("export function", "function")
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
class Element {
  constructor(tag, kind = '') {
    this.tag = tag; this.kind = kind; this.children = []; this.isConnected = true;
    this.classes = new Set(); this.handlers = {}; this.properties = new Map();
    this.style = {setProperty: (key, value) => this.properties.set(key, value)};
    this.classList = {add: value => this.classes.add(value), remove: value => this.classes.delete(value)};
  }
  matches(selector) { return !!this.kind && selector.includes(this.kind); }
  querySelectorAll() { return []; }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  prepend(child) { child.parent = this; this.children.unshift(child); }
  setAttribute() {}
  addEventListener(type, callback) { this.handlers[type] = callback; }
  getBoundingClientRect() { return {left: 10, top: 20}; }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
}
const header = new Element('header', '.app-header');
const oldPane = new Element('section', '.liquid-panel');
const body = new Element('body');
const document = {body, querySelectorAll: () => [header, oldPane], createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)};
const CSS = {supports: (_, value) => value.startsWith('blur')};
const matchMedia = () => ({matches: false});
const navigator = {userAgent: 'Test browser'};
const window = {};
const observed = new Set(), unobserved = [];
class ResizeObserver { observe(target) { observed.add(target); } unobserve(target) { observed.delete(target); unobserved.push(target); } }
const frames = new Map();
let frameId = 0;
const requestAnimationFrame = callback => { frames.set(++frameId, callback); return frameId; };
function frame() { for (const [id, callback] of frames) { frames.delete(id); callback(); } }
function filters(root) { return root.children.reduce((sum, child) => sum + (child.tag === 'filter') + filters(child), 0); }
"""
    script += source
    script += r"""
const TheosGlass = createGlass(scope);
assert.ok(header.classes.has('glass-surface'), 'The top navigation must share the pane material');
assert.equal(filters(body), 2);
oldPane.handlers.pointerdown({pointerType: 'mouse', clientX: 40, clientY: 60});
assert.equal(oldPane.classes.has('glass-pressed'), false);
assert.equal(frames.size, 0, 'Mouse clicks must not start a separate tint response');
oldPane.handlers.pointermove({pointerType: 'mouse', clientX: 40, clientY: 60});
frame();
assert.equal(oldPane.properties.get('--light-x'), '30px');
oldPane.handlers.pointerdown({pointerType: 'touch', clientX: 50, clientY: 80});
assert.equal(oldPane.classes.has('glass-pressed'), true);
frame();
oldPane.handlers.pointerup();
assert.equal(oldPane.classes.has('glass-pressed'), false);
oldPane.isConnected = false;
const fresh = new Element('section', '.liquid-panel');
TheosGlass.enhance(fresh);
assert.equal(filters(body), 2, 'Refreshing data must release the old optical filter');
assert.ok(unobserved.includes(oldPane));
assert.equal(observed.has(oldPane), false);
assert.ok(fresh.classes.has('glass-surface'));
TheosGlass.enhance(fresh);
assert.equal(filters(body), 2, 'Enhancement must be idempotent');
"""
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
