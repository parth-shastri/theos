import { test } from "node:test";
import assert from "node:assert/strict";
import { chatReducer, historyEntries, initialChat } from "../src/state/chat.js";

test("thinking keeps its message identity and duration after completion", () => {
  const started = chatReducer(initialChat, { type: "START", now: 1000 });
  const thinking = chatReducer(started, {
    type: "EVENTS",
    now: 1200,
    events: [{ type: "reasoning", text: "Check the context." }],
  });
  const completed = chatReducer(thinking, {
    type: "EVENTS",
    now: 3400,
    events: [{ type: "assistant_complete", requested_tools: ["read_notes"] }],
  });
  assert.equal(completed.entries[0].id, thinking.entries[0].id);
  assert.equal(completed.entries[0].reasoning, "Check the context.");
  assert.equal(completed.entries[0].streaming, false);
  assert.equal(completed.entries[0].display.duration_ms, 2400);
  assert.equal(thinking.entries[0].streaming, true);
});

test("saved thinking survives hidden OpenUI tool phases without exposing their source", () => {
  const { entries } = historyEntries({
    approvals: [],
    history: [
      {
        type: "assistant",
        text: "Internal presentation",
        reasoning: "Check the notes.",
        display: { openui_hidden: true, duration_ms: 2400 },
      },
      {
        type: "assistant",
        text: "Another hidden presentation without reasoning",
        display: { openui_hidden: true },
      },
      { type: "assistant", reasoning: "Legacy summary." },
    ],
  });
  assert.equal(entries.length, 2);
  assert.equal(entries[0].reasoning, "Check the notes.");
  assert.equal(entries[0].text, "");
  assert.equal(entries[0].presentationHidden, true);
  assert.equal(entries[0].display.duration_ms, 2400);
  assert.equal(entries[1].display, undefined);
});
