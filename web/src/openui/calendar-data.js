const DAY = 86400000;
const propsOf = (value) => value?.props || value || {};

function dateOnly(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
    return null;
  const time = Date.parse(value + "T00:00:00Z");
  return Number.isFinite(time) &&
    new Date(time).toISOString().slice(0, 10) === value
    ? time
    : null;
}

export function calendarInstant(value) {
  if (typeof value !== "string") return null;
  const match = value.match(
    /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$/,
  );
  if (
    !match ||
    dateOnly(match[1]) === null ||
    +match[2] > 23 ||
    +match[3] > 59 ||
    +(match[4] || 0) > 59
  )
    return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

export function validCalendarZone(timezone) {
  if (typeof timezone !== "string" || !timezone) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone }).format(0);
    return true;
  } catch {
    return false;
  }
}

function format(time, timezone, options) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: timezone,
    ...options,
  }).format(time);
}
function dayKey(time, timezone) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(time)
      .map(({ type, value }) => [type, value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}
export function calendarDate(time, timezone) {
  return format(time, timezone, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
function offset(time, timezone) {
  return new Intl.DateTimeFormat("en", {
    timeZone: timezone,
    timeZoneName: "shortOffset",
  })
    .formatToParts(time)
    .find((part) => part.type === "timeZoneName").value;
}
function clock(time, timezone, withOffset = false) {
  return format(time, timezone, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    ...(withOffset ? { timeZoneName: "shortOffset" } : {}),
  });
}
export function calendarRange(start, end, timezone) {
  const shifted = offset(start, timezone) !== offset(end, timezone);
  return `${calendarDate(start, timezone)}, ${clock(start, timezone, shifted)} - ${
    dayKey(start, timezone) === dayKey(end, timezone)
      ? ""
      : calendarDate(end, timezone) + ", "
  }${clock(end, timezone, shifted)}`;
}
export function calendarDuration(milliseconds) {
  if (milliseconds === 0) return "0 min";
  const minutes = Math.round(milliseconds / 60000);
  if (minutes < 1) return "Less than a minute";
  const hours = Math.floor(minutes / 60),
    rest = minutes % 60;
  return [hours ? `${hours} hr` : "", rest ? `${rest} min` : ""]
    .filter(Boolean)
    .join(" ");
}

export function calendarEvent(value, timezone) {
  const event = propsOf(value);
  if (!validCalendarZone(timezone)) return null;
  const allDay = dateOnly(event.start) !== null && dateOnly(event.end) !== null;
  const start = allDay ? dateOnly(event.start) : calendarInstant(event.start);
  const end = allDay ? dateOnly(event.end) : calendarInstant(event.end);
  if (start === null || end === null || end <= start) return null;
  // Date-only values are civil dates. Their exclusive end must not shift with the display timezone.
  const zone = allDay ? "UTC" : timezone;
  const lastDay = allDay ? end - DAY : end;
  const date = calendarDate(start, zone);
  const shifted = !allDay && offset(start, zone) !== offset(end, zone);
  return {
    ...event,
    startTime: start,
    endTime: end,
    allDay,
    day: dayKey(start, zone),
    date:
      dayKey(start, zone) === dayKey(lastDay, zone)
        ? date
        : `${date} - ${calendarDate(lastDay, zone)}`,
    time: allDay
      ? "All day"
      : `${clock(start, zone, shifted)} - ${clock(end, zone, shifted)}`,
    duration: allDay
      ? `${(end - start) / DAY} day${end - start === DAY ? "" : "s"}`
      : calendarDuration(end - start),
  };
}

export function calendarAgenda(events = [], timezone) {
  if (!validCalendarZone(timezone)) return null;
  const valid = [],
    invalid = [];
  for (const value of events) {
    const event = calendarEvent(value, timezone);
    (event ? valid : invalid).push(event || propsOf(value));
  }
  valid.sort(
    (a, b) =>
      a.day.localeCompare(b.day) ||
      Number(b.allDay) - Number(a.allDay) ||
      a.startTime - b.startTime,
  );
  const groups = [];
  for (const event of valid) {
    let group = groups.at(-1);
    if (group?.day !== event.day) {
      group = {
        day: event.day,
        date: calendarDate(event.startTime, event.allDay ? "UTC" : timezone),
        events: [],
      };
      groups.push(group);
    }
    group.events.push(event);
  }
  return { groups, invalid };
}

function mergeIntervals(intervals) {
  const merged = [];
  for (const interval of intervals.sort((a, b) => a.start - b.start)) {
    const previous = merged.at(-1);
    if (previous && interval.start <= previous.end)
      previous.end = Math.max(previous.end, interval.end);
    else merged.push({ ...interval });
  }
  return merged;
}

export function calendarAvailability(
  startValue,
  endValue,
  timezone,
  values = [],
) {
  const start = calendarInstant(startValue),
    end = calendarInstant(endValue);
  if (
    !validCalendarZone(timezone) ||
    start === null ||
    end === null ||
    end <= start
  )
    return null;
  const calendars = values.map((value) => {
    const calendar = propsOf(value);
    const intervals = [];
    let available = Array.isArray(calendar.busy) && !calendar.error;
    for (const value of Array.isArray(calendar.busy) ? calendar.busy : []) {
      const interval = propsOf(value);
      const first = calendarInstant(interval.start),
        last = calendarInstant(interval.end);
      if (first === null || last === null || last <= first) available = false;
      else if (last > start && first < end)
        intervals.push({
          start: Math.max(first, start),
          end: Math.min(last, end),
        });
    }
    return {
      name: calendar.name || "Calendar",
      available,
      error: calendar.error || "Availability unavailable",
      intervals,
    };
  });
  const complete =
    calendars.length > 0 && calendars.every((calendar) => calendar.available);
  const busy = mergeIntervals(
    calendars
      .filter((calendar) => calendar.available)
      .flatMap((calendar) => calendar.intervals),
  );
  const segments = [];
  let cursor = start;
  for (const interval of busy) {
    if (cursor < interval.start)
      segments.push({
        start: cursor,
        end: interval.start,
        status: complete ? "free" : "unknown",
      });
    segments.push({ ...interval, status: "busy" });
    cursor = interval.end;
  }
  if (cursor < end)
    segments.push({
      start: cursor,
      end,
      status: complete ? "free" : "unknown",
    });
  return {
    start,
    end,
    calendars,
    complete,
    segments,
    freeTime: complete
      ? segments
          .filter((segment) => segment.status === "free")
          .reduce((total, segment) => total + segment.end - segment.start, 0)
      : null,
  };
}
