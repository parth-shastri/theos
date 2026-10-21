import { test, expect } from "@playwright/test";
const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";
async function fixture(page, source, version = "theos-openui-2") {
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
  await page.route(`**/api/sessions/${session.id}`, async (route) => {
    const upstream = await route.fetch();
    const data = await upstream.json();
    data.history = [
      { type: "user", content: "Synthetic visual component acceptance" },
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
    await route.fulfill({ response: upstream, json: data });
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
