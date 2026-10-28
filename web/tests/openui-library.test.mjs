import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createParser } from "@openuidev/lang-core";

const schema = JSON.parse(
  readFileSync(
    new URL(
      "../../src/theos/prompts/openui/library-schema.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
test("the generated OpenUI schema parses mixed chart types without missing registrations", () => {
  const source = [
    "root = TheosAnswer(summary, [bars, trend, shares])",
    'summary = AnswerSummary("Three meals total 1,250 kcal.")',
    'bars = BarChart("Meals", ["Breakfast", "Lunch", "Snack"], [calories], "kcal")',
    'calories = ChartSeries("Calories", [420,650,180])',
    'trend = LineChart("Recorded calories", ["Mon", "Tue", "Wed"], [days], "kcal")',
    'days = ChartSeries("Calories", [1200,null,1250])',
    'shares = DonutChart("Meal shares", ["Breakfast", "Lunch", "Snack"], [420,650,180], "kcal")',
  ].join("\n");
  const parsed = createParser(schema, "TheosAnswer").parse(source);
  assert.equal(parsed.root.typeName, "TheosAnswer");
  assert.deepEqual(parsed.meta.errors, []);
  assert.deepEqual(parsed.meta.unresolved, []);
  assert.deepEqual(parsed.meta.orphaned, []);
});
