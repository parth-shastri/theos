import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chatReducer,
  conversationEntries,
  historyEntries,
  initialChat,
} from "../src/state/chat.js";

test("thinking and tool calls keep their order and identity for the whole turn", () => {
  const started = chatReducer(initialChat, { type: "START", now: 1000 });
  const thinking = chatReducer(started, {
    type: "EVENTS",
    now: 1200,
    events: [{ type: "reasoning", text: "Check the context." }],
  });
  const tools = chatReducer(thinking, {
    type: "EVENTS",
    now: 3400,
    events: [
      {
        type: "assistant_complete",
        requested_tools: ["read_notes"],
        tool_calls: [{ id: "first", name: "read_notes", arguments: {} }],
      },
      {
        type: "tool",
        call_id: "first",
        name: "read_notes",
        status: "completed",
        content: "Found notes",
      },
      { type: "thinking" },
      { type: "reasoning", text: "Check the date." },
      { type: "text", text: "Today." },
    ],
  });
  assert.equal(tools.entries[0].running, true);
  const completed = chatReducer(tools, {
    type: "EVENTS",
    now: 9000,
    events: [
      { type: "assistant_complete", text: "Today." },
      { type: "done", duration_ms: 7900 },
    ],
  });
  const [activity, answer] = conversationEntries(completed.entries);
  assert.equal(activity.id, thinking.entries[0].id);
  assert.equal(activity.running, false);
  assert.equal(activity.durationMs, 7900);
  assert.deepEqual(
    activity.rows.map((row) => row.reasoning || row.content),
    ["Check the context.", "Found notes", "Check the date."],
  );
  assert.equal(answer.text, "Today.");
  assert.equal(thinking.entries[1].streaming, true);
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

test("saved turns group tool calls in request order and preserve the duration", () => {
  const { entries } = historyEntries({
    approvals: [],
    history: [
      {
        type: "user",
        content: "Read both calendars.",
        display: { turn_activity: { duration_ms: 8100 } },
      },
      {
        type: "assistant",
        reasoning: "Check calendars.",
        tool_calls: [
          { id: "a", name: "calendar_list_events", arguments: {} },
          { id: "b", name: "calendar_free_busy", arguments: {} },
        ],
      },
      {
        type: "tool_result",
        call_id: "b",
        name: "calendar_free_busy",
        status: "completed",
        content: "Free",
      },
      {
        type: "tool_result",
        call_id: "a",
        name: "calendar_list_events",
        status: "completed",
        content: "One event",
      },
      {
        type: "assistant",
        reasoning: "Combine results.",
        text: "Free from noon.",
      },
      { type: "user", content: "Thanks." },
      { type: "assistant", reasoning: "Keep it short.", text: "Welcome!" },
    ],
  });
  const [, activity, answer, , legacy] = conversationEntries(entries);
  assert.equal(activity.durationMs, 8100);
  assert.deepEqual(
    activity.rows.map((row) => row.reasoning || row.content),
    ["Check calendars.", "One event", "Free", "Combine results."],
  );
  assert.equal(answer.text, "Free from noon.");
  assert.equal(legacy.durationMs, undefined);
  assert.equal(legacy.rows[0].reasoning, "Keep it short.");
});
