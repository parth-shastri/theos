import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chartData,
  chartScale,
  lineRuns,
  compactNumber,
} from "../src/openui/chart-data.js";

test("chart inputs retain missing samples and reject misaligned observations", () => {
  const rows = chartData(
    ["Mon", "Tue", "Wed"],
    [{ props: { name: "Steps", values: [0, null, 7807] } }],
  );
  assert.deepEqual(rows[0].values, [0, null, 7807]);
  assert.equal(
    chartData(["Mon", "Tue"], [{ name: "Steps", values: [7807] }]),
    null,
  );
  assert.equal(
    chartData(["Mon"], [{ name: "Steps", values: [Infinity] }]),
    null,
  );
});
test("chart geometry preserves signed values, zero baselines, and missing-data gaps", () => {
  assert.deepEqual(chartScale([{ values: [-10, null, 30] }]), {
    low: -10,
    high: 30,
    span: 40,
  });
  assert.deepEqual(chartScale([{ values: [0, null] }]), {
    low: 0,
    high: 1,
    span: 1,
  });
  assert.deepEqual(
    lineRuns(
      [1, null, 3, 4],
      (i) => i * 10,
      (v) => 100 - v,
    ),
    [
      [[0, 99]],
      [
        [20, 97],
        [30, 96],
      ],
    ],
  );
});
test("axis labels retain fractional thousands", () => {
  assert.equal(compactNumber(2500), "2,500");
  assert.equal(compactNumber(7500), "7,500");
  assert.equal(compactNumber(12500), "12.5K");
});
