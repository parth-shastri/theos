import { createElement as h, useId, useState } from "react";
import { sourcePresentation } from "./evidence.js";
import {
  calendarAgenda,
  calendarAvailability,
  calendarDuration,
  calendarEvent,
  calendarRange,
} from "./calendar-data.js";

function Heading({ title, timezone, label }) {
  return h("header", { className: "openui-calendar-heading" }, [
    h("div", { key: "title" }, [
      h("span", { className: "openui-calendar-eyebrow", key: "label" }, label),
      h("h3", { key: "name" }, title),
    ]),
    h("span", { className: "openui-calendar-zone", key: "zone" }, timezone),
  ]);
}
function EventLinks({ event }) {
  const links = [
    [event.meeting_url, "Join meeting"],
    [event.url, "Open event"],
  ];
  return h(
    "div",
    { className: "openui-calendar-links" },
    links.map(([url, label]) => {
      const link = sourcePresentation(url);
      return link
        ? h(
            "a",
            {
              key: label,
              href: link.href,
              target: "_blank",
              rel: "noopener noreferrer",
            },
            label,
          )
        : null;
    }),
  );
}
function InvalidEvent({ event }) {
  return h(
    "p",
    { className: "openui-calendar-note" },
    `${event.title || "Event"}: event time unavailable. Check the source details.`,
  );
}
export function Agenda({ title, timezone, events = [], coverage }) {
  const data = calendarAgenda(events, timezone);
  return h("section", { className: "openui-calendar openui-calendar-agenda" }, [
    h(Heading, { key: "heading", title, timezone, label: "Agenda" }),
    !data
      ? h(
          "p",
          { key: "invalid", className: "openui-calendar-note" },
          "A valid display timezone is needed to show this agenda.",
        )
      : [
          !events.length
            ? h(
                "p",
                { key: "empty", className: "openui-calendar-note" },
                "No events in the supplied results.",
              )
            : null,
          ...data.groups.map((group) =>
            h("section", { className: "openui-calendar-day", key: group.day }, [
              h("h4", { key: "date" }, group.date),
              h(
                "ol",
                { key: "events" },
                group.events.map((event, index) =>
                  h("li", { key: index, className: "openui-calendar-event" }, [
                    h(
                      "div",
                      { className: "openui-calendar-when", key: "when" },
                      [
                        h("span", { key: "time" }, event.time),
                        h("small", { key: "duration" }, event.duration),
                      ],
                    ),
                    h(
                      "div",
                      { className: "openui-calendar-event-copy", key: "copy" },
                      [
                        h(
                          "strong",
                          { key: "title" },
                          event.title || "Untitled event",
                        ),
                        event.date !== group.date
                          ? h("p", { key: "dates" }, event.date)
                          : null,
                        event.calendar
                          ? h(
                              "span",
                              {
                                className: "openui-calendar-source",
                                key: "calendar",
                              },
                              event.calendar,
                            )
                          : null,
                        event.status && event.status !== "confirmed"
                          ? h(
                              "span",
                              {
                                className: "openui-calendar-status",
                                key: "status",
                              },
                              event.status === "cancelled"
                                ? "Cancelled"
                                : "Tentative",
                            )
                          : null,
                        event.location
                          ? h("p", { key: "location" }, event.location)
                          : null,
                        h(EventLinks, { key: "links", event }),
                      ],
                    ),
                  ]),
                ),
              ),
            ]),
          ),
          ...data.invalid.map((event, index) =>
            h(InvalidEvent, { event, key: "invalid-" + index }),
          ),
        ],
    h(
      "p",
      { key: "coverage", className: "openui-calendar-note" },
      coverage ||
        `Showing ${events.length} supplied event${events.length === 1 ? "" : "s"}.`,
    ),
  ]);
}

export function EventCard({ event: value, timezone }) {
  const raw = value?.props || value || {};
  const event = calendarEvent(value, timezone);
  return h(
    "section",
    { className: "openui-calendar openui-calendar-event-card" },
    [
      h(Heading, {
        key: "heading",
        title: raw.title || "Untitled event",
        timezone,
        label: "Calendar event",
      }),
      !event
        ? h(InvalidEvent, { key: "invalid", event: raw })
        : [
            h("div", { className: "openui-calendar-date-block", key: "date" }, [
              h("p", { key: "day" }, event.date),
              h("strong", { key: "time" }, event.time),
              h("span", { key: "duration" }, event.duration),
            ]),
            h("dl", { className: "openui-calendar-fields", key: "fields" }, [
              event.calendar
                ? [
                    h("dt", { key: "calendar-label" }, "Calendar"),
                    h("dd", { key: "calendar" }, event.calendar),
                  ]
                : null,
              event.location
                ? [
                    h("dt", { key: "location-label" }, "Location"),
                    h("dd", { key: "location" }, event.location),
                  ]
                : null,
              event.status
                ? [
                    h("dt", { key: "status-label" }, "Status"),
                    h(
                      "dd",
                      { key: "status" },
                      {
                        confirmed: "Confirmed",
                        tentative: "Tentative",
                        cancelled: "Cancelled",
                      }[event.status],
                    ),
                  ]
                : null,
            ]),
          ],
      raw.description
        ? h(
            "details",
            { className: "openui-calendar-description", key: "description" },
            [
              h("summary", { key: "toggle" }, "Event description"),
              h("p", { key: "text" }, raw.description),
            ],
          )
        : null,
      h(EventLinks, { key: "links", event: raw }),
    ],
  );
}

const statusLabel = { free: "Free", busy: "Busy", unknown: "Unconfirmed" };
export function Availability({
  title,
  start,
  end,
  timezone,
  calendars = [],
  coverage,
}) {
  const data = calendarAvailability(start, end, timezone, calendars);
  const [selected, setSelected] = useState(0);
  const inspectionId = useId();
  const index = Math.min(selected, (data?.segments.length || 1) - 1);
  const active = data?.segments[index];
  const describe = (segment) =>
    `${statusLabel[segment.status]}: ${calendarRange(segment.start, segment.end, timezone)} · ${calendarDuration(segment.end - segment.start)}`;
  return h(
    "section",
    { className: "openui-calendar openui-calendar-availability" },
    [
      h(Heading, { key: "heading", title, timezone, label: "Availability" }),
      !data
        ? h(
            "p",
            { className: "openui-calendar-note", key: "invalid" },
            "A valid time range and timezone are needed to show availability.",
          )
        : [
            h(
              "p",
              { className: "openui-calendar-range", key: "range" },
              calendarRange(data.start, data.end, timezone),
            ),
            h(
              "strong",
              { className: "openui-calendar-availability-total", key: "total" },
              data.complete
                ? `${calendarDuration(data.freeTime)} free across all checked calendars`
                : "Availability incomplete",
            ),
            !data.complete
              ? h(
                  "p",
                  { className: "openui-calendar-note", key: "partial" },
                  "Unconfirmed time may contain events from unavailable calendars.",
                )
              : null,
            h(
              "div",
              {
                className: "openui-calendar-timeline",
                role: "group",
                "aria-label": "Inspect availability intervals",
                key: "timeline",
              },
              data.segments.map((segment, i) =>
                h("button", {
                  type: "button",
                  className: "openui-calendar-segment is-" + segment.status,
                  key: i,
                  style: { flexGrow: segment.end - segment.start },
                  "aria-label": describe(segment),
                  "aria-pressed": i === index,
                  "aria-describedby": inspectionId,
                  onClick: () => setSelected(i),
                  onFocus: () => setSelected(i),
                  onKeyDown: (event) => {
                    const buttons =
                      event.currentTarget.parentElement.querySelectorAll(
                        "button",
                      );
                    const next =
                      event.key === "ArrowRight"
                        ? Math.min(i + 1, buttons.length - 1)
                        : event.key === "ArrowLeft"
                          ? Math.max(0, i - 1)
                          : event.key === "Home"
                            ? 0
                            : event.key === "End"
                              ? buttons.length - 1
                              : null;
                    if (next !== null) {
                      event.preventDefault();
                      buttons[next].focus();
                    }
                  },
                }),
              ),
            ),
            h(
              "div",
              { className: "openui-calendar-legend", key: "legend" },
              [...new Set(data.segments.map((segment) => segment.status))].map(
                (status) =>
                  h(
                    "span",
                    { className: "is-" + status, key: status },
                    statusLabel[status],
                  ),
              ),
            ),
            h(
              "p",
              {
                className: "openui-calendar-inspection",
                id: inspectionId,
                "aria-live": "polite",
                key: "inspection",
              },
              active ? describe(active) : "No intervals available.",
            ),
            h(
              "ul",
              { className: "openui-calendar-accounts", key: "calendars" },
              data.calendars.map((calendar, i) =>
                h("li", { key: i }, [
                  h("span", { key: "name" }, calendar.name),
                  h(
                    "span",
                    {
                      className: calendar.available ? "" : "is-unavailable",
                      key: "status",
                    },
                    calendar.available ? "Checked" : calendar.error,
                  ),
                ]),
              ),
            ),
            h("details", { className: "openui-calendar-exact", key: "exact" }, [
              h("summary", { key: "toggle" }, "View time intervals"),
              h(
                "ol",
                { key: "list" },
                data.segments.map((segment, i) =>
                  h("li", { key: i }, describe(segment)),
                ),
              ),
            ]),
          ],
      coverage
        ? h(
            "p",
            { className: "openui-calendar-note", key: "coverage" },
            coverage,
          )
        : null,
    ],
  );
}
