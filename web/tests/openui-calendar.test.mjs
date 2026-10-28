import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createParser } from "@openuidev/lang-core";
import {
  calendarAgenda,
  calendarAvailability,
  calendarDuration,
  calendarEvent,
  calendarInstant,
} from "../src/openui/calendar-data.js";

test("calendar components parse together, including unavailable calendar results", () => {
  const schema = JSON.parse(
    readFileSync(
      new URL(
        "../../src/theos/prompts/openui/library-schema.json",
        import.meta.url,
      ),
    ),
  );
  const source = [
    "root = TheosAnswer(summary, [agenda, card, availability])",
    'summary = AnswerSummary("Partial availability for the requested range.")',
    'event = CalendarEvent("Review", "2026-10-29T09:00:00+05:30", "2026-10-29T10:00:00+05:30", "Work")',
    'agenda = CalendarAgenda("Tomorrow", "Asia/Kolkata", [event])',
    'card = CalendarEventCard(event, "Asia/Kolkata")',
    'busy = CalendarInterval("2026-10-29T09:00:00+05:30", "2026-10-29T10:00:00+05:30")',
    'work = CalendarBusyCalendar("Work", [busy])',
    'missing = CalendarBusyCalendar("Personal", null, "Unavailable")',
    'availability = CalendarAvailability("Free time", "2026-10-29T08:00:00+05:30", "2026-10-29T12:00:00+05:30", "Asia/Kolkata", [work, missing])',
  ].join("\n");
  const parsed = createParser(schema, "TheosAnswer").parse(source);
  assert.deepEqual(parsed.meta.errors, []);
  assert.deepEqual(parsed.meta.unresolved, []);
  assert.deepEqual(parsed.meta.orphaned, []);
  assert.equal(parsed.root.props.sections.length, 3);
  assert.equal(parsed.root.props.sections[2].props.calendars.length, 2);
});

test("calendar grouping preserves exclusive all-day dates and converts timed events", () => {
  const events = [
    {
      title: "Late call",
      start: "2026-10-30T05:30:00Z",
      end: "2026-10-30T06:30:00Z",
    },
    { props: { title: "Leave", start: "2026-10-29", end: "2026-10-31" } },
    { title: "Invalid", start: "2026-02-30", end: "2026-03-02" },
  ];
  const agenda = calendarAgenda(events, "America/Los_Angeles");
  assert.equal(agenda.groups.length, 1);
  assert.equal(agenda.groups[0].day, "2026-10-29");
  assert.deepEqual(
    agenda.groups[0].events.map((event) => event.title),
    ["Leave", "Late call"],
  );
  const leave = agenda.groups[0].events[0];
  assert.equal(leave.time, "All day");
  assert.equal(leave.duration, "2 days");
  assert.match(leave.date, /29 Oct 2026.*30 Oct 2026/);
  assert.equal(agenda.groups[0].events[1].time, "22:30 - 23:30");
  assert.equal(agenda.invalid[0].title, "Invalid");
});

test("ambiguous daylight-saving hours retain their offsets and invalid times stay unavailable", () => {
  const repeated = calendarEvent(
    { start: "2026-11-01T01:30:00-04:00", end: "2026-11-01T01:30:00-05:00" },
    "America/New_York",
  );
  assert.equal(repeated.duration, "1 hr");
  assert.match(repeated.time, /GMT-4.*GMT-5/);
  for (const value of [
    "2026-02-30T10:00:00Z",
    "2026-10-29T24:00:00Z",
    "2026-10-29T10:00:00",
    "nonsense",
  ])
    assert.equal(calendarInstant(value), null);
  assert.equal(
    calendarEvent({ start: "2026-10-29", end: "2026-10-29" }, "UTC"),
    null,
  );
  assert.equal(calendarAgenda([], "Invalid/Zone"), null);
});

test("availability clips, orders, and merges overlapping calendars before finding free time", () => {
  const at = (hour) => `2026-10-29T${hour}:00:00Z`;
  const interval = (first, last) => ({
    props: { start: at(first), end: at(last) },
  });
  const data = calendarAvailability(at("09"), at("17"), "UTC", [
    {
      props: {
        name: "Work",
        busy: [
          interval("15", "18"),
          interval("08", "10"),
          interval("09", "11"),
          interval("11", "12"),
        ],
      },
    },
    { name: "Personal", busy: [interval("13", "14")] },
  ]);
  assert.equal(data.complete, true);
  assert.equal(data.freeTime, 2 * 3600000);
  assert.deepEqual(
    data.segments.map((segment) => [
      new Date(segment.start).getUTCHours(),
      new Date(segment.end).getUTCHours(),
      segment.status,
    ]),
    [
      [9, 12, "busy"],
      [12, 13, "free"],
      [13, 14, "busy"],
      [14, 15, "free"],
      [15, 17, "busy"],
    ],
  );
});

test("failed, missing, and malformed availability never becomes free time", () => {
  const start = "2026-10-29T09:00:00Z",
    end = "2026-10-29T17:00:00Z";
  for (const calendars of [
    [],
    [{ name: "Missing", busy: null }],
    [{ name: "Failed", busy: [], error: "Access denied" }],
    [{ name: "Malformed", busy: [{ start, end: "invalid" }] }],
  ]) {
    const data = calendarAvailability(start, end, "UTC", calendars);
    assert.equal(data.complete, false);
    assert.equal(data.freeTime, null);
    assert.deepEqual(
      data.segments.map((segment) => segment.status),
      ["unknown"],
    );
  }
  const free = calendarAvailability(start, end, "UTC", [
    { name: "Work", busy: [] },
  ]);
  assert.equal(free.freeTime, 8 * 3600000);
  const busy = calendarAvailability(start, end, "UTC", [
    { name: "Work", busy: [{ start, end }] },
  ]);
  assert.equal(busy.freeTime, 0);
  assert.equal(calendarDuration(busy.freeTime), "0 min");
  assert.equal(calendarAvailability(end, start, "UTC", []), null);
});
