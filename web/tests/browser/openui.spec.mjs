import { test, expect } from "@playwright/test";
const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";
async function fixture(
  page,
  source,
  version = "theos-openui-2",
  history = [],
  approvals = [],
) {
  await page.goto("/");
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#workspace")).toBeVisible();
  const response = await page.request.post("/api/sessions", {
    headers: { Origin: new URL(page.url()).origin, "X-Theos-Request": "1" },
    data: { title: "OpenUI component acceptance" },
  });
  expect(response.ok()).toBe(true);
  const session = await response.json(),
    id = "b".repeat(32);
  let state = {},
    summary = "",
    saves = 0;
  const saved = await page.request.get(`/api/sessions/${session.id}`);
  expect(saved.ok()).toBe(true);
  const snapshot = await saved.json();
  await page.route(`**/api/sessions/${session.id}`, async (route) => {
    const data = { ...snapshot };
    data.approvals = approvals;
    data.history = [
      { type: "user", content: "Synthetic visual component acceptance" },
      ...history,
      {
        type: "assistant",
        text: source,
        display: {
          format: "openui-lang",
          library_version: version,
          openui_message_id: id,
          openui_state: state,
          openui_summary: summary,
        },
      },
    ];
    await route.fulfill({ json: data });
  });
  await page.route(
    `**/api/sessions/${session.id}/openui-state`,
    async (route) => {
      const data = route.request().postDataJSON();
      state = data.state;
      summary = data.summary;
      saves++;
      await route.fulfill({ json: { saved: true } });
    },
  );
  await page.reload();
  await expect(page.locator(".theos-openui-answer")).toBeVisible();
  return { state: () => state, summary: () => summary, saves: () => saves };
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("approval reviews keep decisions visible and recover from a rejected submission", async ({
  page,
}, testInfo) => {
  const pending = [
    {
      id: "synthetic-approval",
      call_id: "synthetic-call",
      tool: "gmail_send_draft",
      label: "Send the reviewed draft",
      arguments: JSON.stringify({ draft_id: "synthetic-draft" }),
      review: [
        {
          label: "To",
          text: "review@example.com",
          kind: "text",
          group: "Email",
        },
        {
          label: "Subject",
          text: "Tomorrow's project review",
          kind: "text",
          group: "Email",
        },
        {
          label: "Message",
          text: Array(10)
            .fill(
              "Please review the attached project notes before tomorrow's meeting. The final section lists the decisions that still need your input.",
            )
            .join("\n\n"),
          kind: "markdown",
          group: "Email",
        },
        {
          label: "Draft ID",
          text: "synthetic-draft",
          kind: "code",
          technical: true,
          group: "Identifiers",
        },
      ],
    },
  ];
  await fixture(
    page,
    'root = TheosAnswer(AnswerSummary("The draft is ready for review."))',
    "theos-openui-2",
    [],
    pending,
  );
  const card = page.getByRole("article", {
    name: "Send the reviewed draft",
    exact: true,
  });
  const approve = card.getByRole("button", { name: "Approve", exact: true });
  const deny = card.getByRole("button", { name: "Deny", exact: true });
  await expect(approve).toBeInViewport();
  await expect(deny).toBeInViewport();
  await expect(card.getByText("synthetic-draft", { exact: true })).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath("approval-review.png") });
  await card.getByText("Exact tool arguments", { exact: true }).click();
  await expect(card.locator("pre").last()).toHaveText(
    '{\n  "draft_id": "synthetic-draft"\n}',
  );
  await expect(approve).toBeInViewport();
  await expect(deny).toBeInViewport();
  const decisions = [];
  let release;
  await page.route("**/approvals/synthetic-approval", async (route) => {
    decisions.push(route.request().postDataJSON().approved);
    await new Promise((resolve) => {
      release = resolve;
    });
    if (decisions.length === 1)
      await route.fulfill({
        status: 409,
        json: { detail: "The draft changed. Review again." },
      });
    else {
      pending.splice(0);
      await route.fulfill({
        contentType: "text/event-stream",
        body: 'data: {"type":"done"}\n\n',
      });
    }
  });
  await approve.click();
  await expect(approve).toBeDisabled();
  await expect(deny).toBeDisabled();
  await expect.poll(() => decisions.length).toBe(1);
  release();
  await expect(approve).toBeEnabled();
  await expect(card).toBeVisible();
  await deny.click();
  await expect(approve).toBeDisabled();
  await expect.poll(() => decisions.length).toBe(2);
  release();
  await expect(card).toHaveCount(0);
  expect(decisions).toEqual([true, false]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("text summaries use readable rows and completed thinking has no separate timestamp", async ({
  page,
}, testInfo) => {
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [plan])",
      'summary = AnswerSummary("A short plan for tomorrow.")',
      'plan = SummaryCard("Tomorrow", [first, second])',
      'first = SummaryFact("Morning", "Review the notes and prepare the draft before the meeting.")',
      'second = SummaryFact("Afternoon", "Share the draft and collect feedback from the team.")',
    ].join("\n"),
    "theos-openui-1",
    [
      {
        type: "assistant",
        text: "Hidden tool-phase presentation",
        reasoning: "I checked the saved context before preparing the plan.",
        display: {
          format: "openui-lang",
          openui_hidden: true,
          duration_ms: 2400,
          created_at: 1793188800,
        },
      },
      { type: "assistant", reasoning: "A legacy summary without timing." },
    ],
  );
  const thought = page.locator(".message.assistant").filter({
    has: page.getByText("Thought for 2.4 s", { exact: true }),
  });
  await expect(thought.locator(".message-footer")).toBeHidden();
  await expect(thought.locator(".role")).toBeHidden();
  await expect(thought.locator(".thinking-body")).toBeHidden();
  await thought.locator("summary").click();
  await expect(thought.locator(".thinking-body")).toContainText(
    "I checked the saved context",
  );
  await expect(page.locator(".thinking-label").last()).toHaveText("Thought");
  await expect(page.getByText("Hidden tool-phase presentation")).toHaveCount(0);
  const rows = page.locator(".openui-summary-fact");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText(
    "Review the notes and prepare the draft before the meeting.",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("summary-and-thinking.png"),
  });
  await page.reload();
  await expect(page.locator(".thinking-label").first()).toHaveText(
    "Thought for 2.4 s",
  );
  await expect(page.locator(".thinking-body").first()).toBeHidden();
});

test("streamed thinking becomes a completed thought in the same disclosure", async ({
  page,
}) => {
  await fixture(page, 'root = TheosAnswer(AnswerSummary("Earlier answer."))');
  await page.evaluate(() => {
    const fetch = window.fetch.bind(window);
    window.fetch = (url, options) => {
      if (!String(url).endsWith("/turn")) return fetch(url, options);
      return Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              const send = (event) =>
                controller.enqueue(
                  new TextEncoder().encode(
                    `data: ${JSON.stringify(event)}\n\n`,
                  ),
                );
              send({ type: "thinking" });
              send({ type: "reasoning", text: "Check the context first." });
              window.finishThinking = () => {
                send({
                  type: "assistant_complete",
                  reasoning: "Check the context first.",
                  requested_tools: ["read_notes"],
                  display: { duration_ms: 2400, created_at: 1793188800 },
                });
                send({ type: "done" });
                controller.close();
              };
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        ),
      );
    };
  });
  await page.locator("#message").fill("Check the context.");
  await page.locator("#send").click();
  const thought = page.locator(".thinking");
  await expect(thought.locator("summary")).toHaveText("Thinking…");
  await expect(page.locator(".turn-activity")).toHaveCount(0);
  await thought.locator("summary").click();
  const disclosure = await thought.elementHandle();
  await page.evaluate(() => window.finishThinking());
  await expect(thought.locator("summary")).toHaveText("Thought for 2.4 s");
  expect(await disclosure.evaluate((element) => element.isConnected)).toBe(
    true,
  );
  await expect(thought).toHaveAttribute("open", "");
  await expect(thought.locator(".thinking-body")).toHaveText(
    "Check the context first.",
  );
  await expect(thought.locator("..").locator(".message-footer")).toBeHidden();
  await expect(page.locator("#send")).toBeEnabled();
});

test("calendar agenda, event details, and availability preserve source dates and support keyboard inspection", async ({
  page,
}, testInfo) => {
  const errors = [],
    writes = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/turn$/.test(request.url()))
      writes.push(request.url());
  });
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [agenda, card, available])",
      'summary = AnswerSummary("Four returned events and availability from two checked calendars. The event list has another page.")',
      'review = CalendarEvent("Project review", "2026-10-29T10:30:00+05:30", "2026-10-29T11:15:00+05:30", "Work", "Meeting room", "https://meet.google.com/abc-defg-hij", "https://calendar.google.com/calendar/event?eid=synthetic", "Discuss the draft and the next steps.\\nBring your project notes.", "confirmed")',
      'leave = CalendarEvent("Team offsite", "2026-10-29", "2026-10-31", "Team")',
      'late = CalendarEvent("Overnight support", "2026-10-29T23:30:00+05:30", "2026-10-30T00:30:00+05:30", "Work")',
      'next = CalendarEvent("Morning walk", "2026-10-30T03:30:00Z", "2026-10-30T04:00:00Z", "Personal")',
      'agenda = CalendarAgenda("Your next few days", "Asia/Kolkata", [next, review, leave, late], "29-30 October · first four events · more events available")',
      'card = CalendarEventCard(review, "Asia/Kolkata")',
      'first = CalendarInterval("2026-10-29T10:30:00+05:30", "2026-10-29T11:15:00+05:30")',
      'overlap = CalendarInterval("2026-10-29T11:00:00+05:30", "2026-10-29T12:00:00+05:30")',
      'afternoon = CalendarInterval("2026-10-29T15:00:00+05:30", "2026-10-29T16:00:00+05:30")',
      'work = CalendarBusyCalendar("Work", [first, overlap])',
      'personal = CalendarBusyCalendar("Personal", [afternoon])',
      'available = CalendarAvailability("Time to meet", "2026-10-29T09:00:00+05:30", "2026-10-29T18:00:00+05:30", "Asia/Kolkata", [work, personal], "Availability checked for Work and Personal only.")',
    ].join("\n"),
    "theos-openui-3",
  );
  const agenda = page.locator(".openui-calendar-agenda");
  await expect(agenda.locator(".openui-calendar-day h4")).toHaveCount(2);
  await expect(agenda.locator(".openui-calendar-event").first()).toContainText(
    "Team offsite",
  );
  await expect(agenda).toContainText("All day");
  await expect(agenda).toContainText("2 days");
  await expect(agenda).toContainText("Thu, 29 Oct 2026 - Fri, 30 Oct 2026");
  await expect(agenda.locator(".openui-calendar-event").last()).toContainText(
    "09:00 - 09:30",
  );
  await expect(agenda).toContainText("more events available");
  const card = page.locator(".openui-calendar-event-card");
  await expect(card).toContainText("45 min");
  await expect(
    card.getByRole("link", { name: "Join meeting", exact: true }),
  ).toHaveAttribute("href", "https://meet.google.com/abc-defg-hij");
  await expect(
    card.getByRole("link", { name: "Open event", exact: true }),
  ).toHaveAttribute("rel", "noopener noreferrer");
  await card.getByText("Event description", { exact: true }).click();
  await expect(card.locator(".openui-calendar-description p")).toContainText(
    "Bring your project notes.",
  );
  const availability = page.locator(".openui-calendar-availability");
  await expect(availability).toContainText(
    "6 hr 30 min free across all checked calendars",
  );
  await availability.locator(".openui-calendar-segment").first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    availability.locator(".openui-calendar-inspection"),
  ).toContainText("Busy: Thu, 29 Oct 2026, 10:30 - 12:00 · 1 hr 30 min");
  await page.keyboard.press("End");
  await expect(
    availability.locator(".openui-calendar-inspection"),
  ).toContainText("16:00 - 18:00");
  await availability.getByText("View time intervals", { exact: true }).click();
  await expect(availability.locator(".openui-calendar-exact li")).toHaveCount(
    5,
  );
  await availability.getByText("View time intervals", { exact: true }).click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  for (const [component, filename] of [
    [agenda, "calendar-agenda"],
    [card, "calendar-event"],
    [availability, "calendar-availability"],
  ]) {
    await component.evaluate((element) => {
      const pane = document.getElementById("messages");
      pane.scrollTop +=
        element.getBoundingClientRect().top -
        pane.getBoundingClientRect().top -
        85;
    });
    await page.screenshot({ path: testInfo.outputPath(filename + ".png") });
  }
  await page.reload();
  await expect(page.locator(".openui-calendar-agenda")).toBeVisible();
  await expect(page.locator(".openui-fallback")).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
});

test("calendar views keep empty, unavailable, invalid, and unsafe source data explicit", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [agenda, card, available])",
      'summary = AnswerSummary("No events in this page. Personal availability could not be checked.")',
      'agenda = CalendarAgenda("Search results", "Pacific/Honolulu", [], "Empty page · another page is available")',
      'event = CalendarEvent("Untrusted event", "2026-02-30T10:00:00Z", "2026-03-01T11:00:00Z", "Work", "", "javascript:alert(1)", "https://user:password@example.com/event", "<img src=x onerror=alert(1)>")',
      'card = CalendarEventCard(event, "UTC")',
      'busy = CalendarInterval("2026-10-29T10:00:00Z", "2026-10-29T11:00:00Z")',
      'work = CalendarBusyCalendar("Work", [busy])',
      'personal = CalendarBusyCalendar("Personal", null, "Access unavailable")',
      'available = CalendarAvailability("Checked availability", "2026-10-29T09:00:00Z", "2026-10-29T12:00:00Z", "UTC", [work, personal])',
    ].join("\n"),
    "theos-openui-3",
  );
  await expect(page.locator(".openui-calendar-agenda")).toContainText(
    "No events in the supplied results.",
  );
  await expect(page.locator(".openui-calendar-agenda")).toContainText(
    "another page is available",
  );
  const card = page.locator(".openui-calendar-event-card");
  await expect(card).toContainText("event time unavailable");
  await expect(card.locator("a")).toHaveCount(0);
  await card.getByText("Event description", { exact: true }).click();
  await expect(card.locator(".openui-calendar-description p")).toHaveText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(card.locator("img")).toHaveCount(0);
  const availability = page.locator(".openui-calendar-availability");
  await expect(availability).toContainText("Availability incomplete");
  await expect(availability).toContainText("Access unavailable");
  await expect(availability.locator(".is-free")).toHaveCount(0);
  await expect(
    availability.locator(".openui-calendar-segment.is-unknown"),
  ).toHaveCount(2);
  await expect(
    availability.locator(".openui-calendar-segment.is-busy"),
  ).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("health status notices remain in the chat when the conversation drawer toggles", async ({
  page,
}) => {
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [stats, note])",
      'summary = AnswerSummary("Synthetic health snapshot.")',
      'stats = SummaryCard("Activity", [steps, distance])',
      'steps = SummaryFact("Steps", "7,807")',
      'distance = SummaryFact("Distance", "5.70 km")',
      'note = StatusNotice("info", "Calendar data is unavailable.")',
    ].join("\n"),
    "theos-openui-1",
  );
  const toggle = page.getByRole("button", {
    name: "Toggle conversation sidebar",
    exact: true,
  });
  if ((await toggle.getAttribute("aria-expanded")) === "true")
    await toggle.click();
  await expect(page.locator(".openui-status-notice")).toBeVisible();
  expect(
    await page
      .locator(".openui-status-notice")
      .evaluate((e) => getComputedStyle(e).position),
  ).toBe("static");
  await toggle.click();
  await expect(page.locator("#sidebar")).toBeVisible();
  await expect(page.locator("#new-session")).toBeVisible();
  const rect = await page.locator(".openui-status-notice").evaluate((e) => ({
    height: e.getBoundingClientRect().height,
    position: getComputedStyle(e).position,
  }));
  expect(rect.position).toBe("static");
  expect(rect.height).toBeLessThan(160);
  expect(
    await page
      .locator("#sidebar")
      .evaluate((e) => e.getBoundingClientRect().left),
  ).toBeGreaterThanOrEqual(0);
});

test("reminder controls share the glass pickers and retain edits after reload", async ({
  page,
}) => {
  const saved = await fixture(
    page,
    [
      "root = TheosAnswer(summary, [form])",
      'summary = AnswerSummary("Review this reminder draft before submitting.")',
      'form = ScheduleReminderForm("Drink water", "2030-01-15", "10:30", "Asia/Kolkata", "none", [])',
    ].join("\n"),
    "theos-openui-1",
  );
  await page
    .locator('input[name="reminder_text"]')
    .fill("Edited water reminder");
  await expect
    .poll(() => saved.state().reminder_text)
    .toBe("Edited water reminder");
  expect(saved.state().reminder_date).toBe("2030-01-15");
  expect(saved.summary()).toBe("Review this reminder draft before submitting.");
  await page
    .getByRole("button", { name: "Repeat: Never", exact: true })
    .click();
  await page
    .getByRole("option", { name: "Selected days", exact: true })
    .click();
  await expect(
    page.getByRole("listbox", { name: "Repeat", exact: true }),
  ).toBeHidden();
  await page.locator('.openui-weekday-options input[value="MO"]').check();
  await page
    .getByRole("button", { name: "Choose reminder date", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Choose reminder date", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /Wednesday, January 16, 2030/ })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Choose reminder date", exact: true }),
  ).toBeHidden();
  await expect.poll(() => saved.state().reminder_date).toBe("2030-01-16");
  await page.reload();
  await expect(page.locator('input[name="reminder_text"]')).toHaveValue(
    "Edited water reminder",
  );
  await expect(page.locator('input[name="reminder_date"]')).toHaveValue(
    "2030-01-16",
  );
  await expect(
    page.getByRole("button", { name: "Repeat: Selected days", exact: true }),
  ).toBeVisible();
  await expect(
    page.locator('.openui-weekday-options input[value="MO"]'),
  ).toBeChecked();
  await expect
    .poll(() => saved.state().reminder_text)
    .toBe("Edited water reminder");
  expect(saved.state().reminder_weekdays).toEqual(["MO"]);
});

test("OpenUI charts expose exact values, keyboard inspection, and missing samples", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [metrics, bars, line, donut, progress, table])",
      'summary = AnswerSummary("Synthetic visual acceptance with exact values and one missing day.")',
      'metrics = MetricGrid("Activity overview", [steps, sleep], "Synthetic values")',
      'steps = Metric("Steps", "7,807", "steps", "Recorded today")',
      'sleep = Metric("Sleep", "6 hr 57 min", "", "Recorded last night")',
      'bars = BarChart("Calories by meal", ["Breakfast", "Lunch", "Snack"], [calories], "kcal")',
      'calories = ChartSeries("Calories", [420,650,180])',
      'line = LineChart("Steps over time", ["Mon", "Tue", "Wed", "Thu"], [days], "steps")',
      'days = ChartSeries("Steps", [6000,null,7807,8100])',
      'donut = DonutChart("Meal shares", ["Breakfast", "Lunch", "Snack"], [420,650,180], "kcal")',
      'progress = ProgressCard("Daily calories", 1250, 2200, "kcal", "User-supplied goal")',
      'table = DataTable("Exact comparison", ["Meal", "Calories"], [["Breakfast",420],["Lunch",650],["Snack",180]])',
    ].join("\n"),
  );
  await expect(page.locator(".openui-chart")).toHaveCount(2);
  const bar = page.locator(".openui-chart").first();
  await bar
    .getByRole("button", { name: "Breakfast: Calories 420 kcal", exact: true })
    .focus();
  await page.keyboard.press("ArrowRight");
  await expect(bar.locator(".openui-chart-inspection")).toContainText(
    "Lunch · Calories: 650 kcal",
  );
  const line = page.locator(".openui-chart").nth(1);
  await line
    .getByRole("button", { name: "Tue: Steps No data steps", exact: true })
    .click();
  await expect(line.locator(".openui-chart-inspection")).toContainText(
    "No data",
  );
  await page.locator(".openui-donut-legend button").nth(1).click();
  await expect(page.locator(".openui-donut-total strong")).toHaveText("650");
  await expect(page.locator(".openui-progress-ring")).toHaveAttribute(
    "aria-label",
    /1,250 of 2,200/,
  );
  await bar.locator(".openui-exact-values summary").click();
  await expect(bar.locator("table")).toContainText("650");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("search evidence cards clean operator syntax and retain exact search details", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [sources])",
      'summary = AnswerSummary("Example source results for UI acceptance.")',
      'sources = EvidenceList("OpenUI integration examples", "site:openui.com/examples OpenUI integration -site:spam.example", [first, second, unsafe])',
      'first = EvidenceItem("LangGraph Platform", "https://www.openui.com/examples", "Excerpt: A documented integration example.", "https://www.openui.com/examples", true)',
      'second = EvidenceItem("Vercel AI SDK", "https://www.openui.com/examples", "A second documented integration.", "source-12", true)',
      'unsafe = EvidenceItem("Unavailable source", "javascript:alert(1)", "Unsafe links stay as text.", "", true)',
    ].join("\n"),
    "theos-openui-1",
  );
  await expect(page.locator(".openui-source-count")).toHaveText("3 results");
  await expect(page.locator(".openui-search-terms")).toHaveText(
    "Search termsOpenUI integration",
  );
  await expect(page.locator(".openui-search-filters")).toContainText(
    "From openui.com/examples",
  );
  await expect(page.locator(".openui-search-filters")).toContainText(
    "Excluding spam.example",
  );
  await expect(page.locator(".openui-evidence-item")).toHaveCount(3);
  await expect(page.locator(".openui-source-domain").first()).toHaveText(
    "openui.com",
  );
  await expect(page.locator(".openui-evidence-snippet").first()).toHaveText(
    "A documented integration example.",
  );
  await expect(page.locator(".openui-source-reference")).toHaveText(
    "Reference: source-12",
  );
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.locator(".openui-search-details code")).toBeHidden();
  await page.getByText("Search details", { exact: true }).click();
  await expect(page.locator(".openui-search-details code")).toHaveText(
    "site:openui.com/examples OpenUI integration -site:spam.example",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("search thumbnails and logos match the source cards and collapse failed media", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const requests = [];
  await page.route("**/api/search-image?**", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    const remote = params.get("url") || params.get("site");
    requests.push(remote);
    if (remote.includes("missing"))
      return route.fulfill({ status: 404, body: "" });
    return route.fulfill({
      status: 200,
      contentType: "image/png",
      path: "public/static/brand-light.png",
    });
  });
  await fixture(
    page,
    [
      "root = TheosAnswer(summary, [sources])",
      'summary = AnswerSummary("Image and logo acceptance.")',
      'sources = EvidenceList("Visual search results", "site:example.com visual search", [photo, broken, legacy])',
      'photo = EvidenceItem("Source with a photo", "https://example.com/article", "A source excerpt with a genuine thumbnail.", "", true, "https://cdn.example.com/photo.png", "Source preview", "https://example.com/logo.png")',
      'broken = EvidenceItem("Unavailable image", "https://example.com/missing", "This excerpt stays readable when the image fails.", "", true, "https://cdn.example.com/missing.png", "Unavailable", "https://example.com/missing.ico")',
      'legacy = EvidenceItem("Older saved result", "https://example.com/older", "Saved answers still render.", "", true)',
    ].join("\n"),
  );
  const first = page.locator(".openui-evidence-item").first();
  await first.scrollIntoViewIfNeeded();
  const preview = first.locator(".openui-result-preview img");
  await expect(preview).toHaveAttribute("alt", "Source preview");
  await expect
    .poll(() => preview.evaluate((img) => img.complete && img.naturalWidth > 0))
    .toBe(true);
  const imageGeometry = await preview.evaluate((img) => ({
    width: img.getBoundingClientRect().width,
    containerWidth: img.parentElement.clientWidth,
    margin: getComputedStyle(img).marginTop,
  }));
  expect(
    Math.abs(imageGeometry.width - imageGeometry.containerWidth),
  ).toBeLessThan(2);
  expect(imageGeometry.margin).toBe("0px");
  const logo = first.locator(".openui-source-mark img");
  await expect
    .poll(() => logo.evaluate((img) => img.complete && img.naturalWidth > 0))
    .toBe(true);
  expect(await logo.evaluate((img) => getComputedStyle(img).marginTop)).toBe(
    "0px",
  );
  await expect(first.locator(".openui-result-preview")).toHaveAttribute(
    "href",
    "https://example.com/article",
  );
  await first.locator(".openui-result-preview").focus();
  await expect(first.locator(".openui-result-preview")).toBeFocused();
  const broken = page.locator(".openui-evidence-item").nth(1);
  await broken.scrollIntoViewIfNeeded();
  await expect
    .poll(() => requests.filter((url) => url.includes("missing")).length)
    .toBe(2);
  await expect(broken.locator("img")).toHaveCount(0);
  await expect(broken.locator(".openui-source-mark")).toHaveText("E");
  await expect(broken.locator(".openui-evidence-snippet")).toContainText(
    "stays readable",
  );
  await expect(
    page.locator('.openui-evidence-item img[src^="https:"]'),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.reload();
  await expect(page.locator(".openui-evidence-item")).toHaveCount(3);
  expect(errors).toEqual([]);
});
