"""Exercise React chart geometry, selection, missing prices, and breakdowns."""

import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_chart_interaction_preserves_unknown_prices_and_full_breakdowns():
    script = r"""
import assert from 'node:assert/strict';
import {dailyGeometry, rankingData, nextChartDay, money} from './web/src/state/chartData.js';
const daily = [10, 0, 7, 4, 2, 9, 0].map((requests, i) => ({
  date: '2026-10-' + String(i + 1).padStart(2, '0'),
  requests, input_tokens: requests * 100, output_tokens: requests * 20,
  cost: [0.000006, 0, null, 0.000004, 0.000002, null, 0][i],
  unpriced_requests: [2, 5].includes(i) ? requests : 0,
}));
const models = Array.from({length: 8}, (_, i) => ({
  model: 'model-' + i, requests: 8 - i, input_tokens: (8 - i) * 1000, output_tokens: (8 - i) * 200,
}));
const costs = dailyGeometry(daily, true, 600);
assert.equal(daily.filter(row => row.cost === null).length, 2);
assert.equal(costs.runs.length, 3, 'Unknown prices must split the line');
assert.equal(costs.runs.filter(run => run.length > 1).length, 2, 'Area fills must not bridge unknown days');
assert.equal(money(daily[0].cost), '$0.000006');
let selected = 2;
assert.equal(money(daily[selected].cost), 'Unavailable');
assert.equal(daily[selected].unpriced_requests, 7);
selected = nextChartDay(selected, 'ArrowRight', daily.length);
assert.equal(selected, 3);
assert.equal(money(daily[selected].cost), '$0.000004');
selected = nextChartDay(selected, 'End', daily.length);
assert.equal(selected, 6);
selected = nextChartDay(selected, 'Home', daily.length);
assert.equal(selected, 0);
for (const cost of [false, true]) {
  const resized = dailyGeometry(daily, cost, 220);
  assert.equal(resized.height, 232);
  assert.ok(daily.every((row, index) => Number.isFinite(resized.x(index)) && Number.isFinite(resized.y(row.cost || 0))));
}
assert.equal(selected, 0, 'Responsive geometry must not change React selection state');
const ranking = rankingData(models, true);
assert.equal(ranking.visible.length, 7);
assert.equal(ranking.visible.at(-1).model, 'Other models (2)');
assert.equal(ranking.value(ranking.visible.at(-1)), 3600);
for (const row of ranking.visible) assert.ok(ranking.value(row) / ranking.maximum * 100 <= 100.000001);
assert.equal(ranking.exactRows.length, 8, 'Exact data must retain every model');
assert.deepEqual(ranking.exactRows, models);
assert.equal(daily[3].input_tokens, 400);
const empty = dailyGeometry(daily.map(row => ({...row, requests: 0, cost: 0, unpriced_requests: 0})), false, 220);
assert.equal(empty.insight, 'No model requests in this period.');
assert.deepEqual(rankingData([], false).visible, []);
const unknown = dailyGeometry(daily.map(row => ({...row, cost: null, unpriced_requests: row.requests})), true, 220);
assert.equal(unknown.insight, 'No prices recorded for these requests.');
assert.equal(money(null), 'Unavailable');
assert.deepEqual(unknown.runs, []);
"""
    result = subprocess.run(
        ["node", "--input-type=module"], input=script, text=True, capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
