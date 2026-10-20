"""Exercise native chart selection, missing prices, and responsive redraws."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_chart_interaction_preserves_unknown_prices_and_full_breakdowns():
    source = Path("web/src/runtime/charts.js").read_text().replace("export function", "function")
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
function all(root, predicate) {
  return root.children.flatMap(child => [ ...(predicate(child) ? [child] : []), ...all(child, predicate) ]);
}
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.style = {}; this.text = ''; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(''); }
  set className(value) { this.attributes.class = value; }
  get className() { return this.attributes.class || ''; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.text = ''; this.children = children; }
  querySelector(tag) { return all(this, child => child.tag === tag)[0]; }
  focus() { document.activeElement = this; this.onfocus?.(); }
  get classList() {
    return {toggle: (value, enabled) => {
      const values = new Set(this.className.split(' ').filter(Boolean));
      enabled ? values.add(value) : values.delete(value);
      this.className = [...values].join(' ');
    }};
  }
}
const document = {createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)};
const window = {};
const observers = [];
class ResizeObserver {
  constructor(callback) { this.callback = callback; observers.push(this); }
  observe(target) { this.target = target; }
  disconnect() { this.disconnected = true; }
}
const byClass = (root, name) => all(root, child => child.className.split(' ').includes(name));
const daily = [10, 0, 7, 4, 2, 9, 0].map((requests, i) => ({
  date: `2026-10-${String(i + 1).padStart(2, '0')}`,
  requests, input_tokens: requests * 100, output_tokens: requests * 20,
  cost: [0.000006, 0, null, 0.000004, 0.000002, null, 0][i],
  unpriced_requests: [2, 5].includes(i) ? requests : 0,
}));
const models = Array.from({length: 8}, (_, i) => ({
  model: `model-${i}`, requests: 8 - i, input_tokens: (8 - i) * 1000, output_tokens: (8 - i) * 200,
}));
const tools = Array.from({length: 8}, (_, i) => ({tool: `tool-${i}`, calls: 8 - i}));
const data = {days: 7, daily, models, tools, totals: {
  requests: 32, cost: 0.000012, unpriced_requests: 16, input_tokens: 36000, output_tokens: 7200,
}};
"""
    script += source
    script += r"""
const TheosCharts = createCharts(scope);
const grid = TheosCharts.activity(data);
const requests = byClass(grid, 'chart-requests')[0];
const costs = byClass(grid, 'chart-cost')[0];
assert.equal(byClass(costs, 'cost-unknown').length, 2);
assert.equal(byClass(costs, 'cost-line').length, 3, 'Unknown prices must split the line');
assert.equal(byClass(costs, 'cost-area').length, 2, 'Area fills must not bridge unknown days');
assert.ok(costs.textContent.includes('$0.000006'), 'Tiny costs must remain readable');
let hits = byClass(costs, 'chart-hit');
assert.equal(hits.filter(hit => hit.getAttribute('tabindex') === '0').length, 1);
hits[2].onclick();
assert.ok(byClass(costs, 'chart-inspection')[0].textContent.includes('Unavailable'));
assert.ok(byClass(costs, 'chart-inspection')[0].textContent.includes('7 unpriced'));
let prevented = 0;
hits[2].onkeydown({key: 'ArrowRight', preventDefault() { prevented++; }});
assert.equal(document.activeElement, hits[3]);
assert.ok(byClass(costs, 'chart-inspection')[0].textContent.includes('$0.000004'));
hits[3].onkeydown({key: 'End', preventDefault() { prevented++; }});
assert.equal(document.activeElement, hits[6]);
hits[6].onkeydown({key: 'Home', preventDefault() { prevented++; }});
assert.equal(document.activeElement, hits[0]);
assert.equal(prevented, 3);
for (const observer of observers) observer.callback([{contentRect: {width: 220}}]);
assert.ok(!grid.textContent.includes('NaN'));
assert.ok(all(grid, child => child.tag === 'svg').every(svg => svg.getAttribute('viewBox') === '0 0 220 232'));
hits = byClass(costs, 'chart-hit');
assert.equal(hits[0].getAttribute('tabindex'), '0', 'Selection must survive a redraw');
const modelCard = byClass(grid, 'chart-models')[0];
const ranks = byClass(modelCard, 'rank-item');
assert.equal(ranks.length, 7);
assert.ok(ranks.at(-1).textContent.includes('Other models (2)'));
assert.ok(ranks.at(-1).textContent.includes((3600).toLocaleString()));
for (const rank of ranks) {
  const widths = [...byClass(rank, 'rank-input'), ...byClass(rank, 'rank-output')].map(span => Number(span.style.width.replace('%', '')));
  assert.ok(widths.reduce((sum, value) => sum + value, 0) <= 100.000001);
}
assert.equal(all(modelCard, child => child.tag === 'tbody')[0].children.length, 8, 'Exact data must retain every model');
byClass(requests, 'chart-hit')[3].onclick();
assert.ok(byClass(requests, 'chart-inspection')[0].textContent.includes('400 input'));
const oldObservers = [...observers];
const empty = TheosCharts.activity({...data, daily: daily.map(row => ({...row, requests: 0, cost: 0, unpriced_requests: 0, input_tokens: 0, output_tokens: 0})), models: [], tools: [], totals: {requests: 0, cost: 0, unpriced_requests: 0, input_tokens: 0, output_tokens: 0}});
assert.ok(oldObservers.every(observer => observer.disconnected));
assert.ok(empty.textContent.includes('No model requests in this period.'));
assert.ok(empty.textContent.includes('No tool calls in this period.'));
const unknown = TheosCharts.activity({...data, daily: daily.map(row => ({...row, cost: null, unpriced_requests: row.requests})), totals: {...data.totals, cost: null}});
assert.equal(byClass(byClass(unknown, 'chart-cost')[0], 'chart-value')[0].textContent, 'Unavailable');
"""
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
