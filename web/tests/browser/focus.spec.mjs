import { test, expect } from "@playwright/test";

const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";

test("the Focus inbox keeps alerts out of the conversation", async ({
  page,
}, info) => {
  const path = "/api/notifications/browser";
  const notices = [
    {
      id: "reminder",
      source: "reminder",
      text: "Review the schedule",
      created: 1794630600,
    },
    ...[1, 2].map((run) => ({
      id: "github-" + run,
      source: "github",
      text: "Workflow failed in sample/theos: Theos CI",
      url: "https://github.com/sample/theos/actions/runs/" + run,
      created: 1794627000 + run,
    })),
  ];
  let items = notices;
  let previous = [];
  await page.route("**" + path + "**", async (route) => {
    const request = route.request();
    if (request.url().includes("/history")) {
      await route.fulfill({
        json: {
          items: [...notices]
            .sort((left, right) => right.created - left.created)
            .map((notice) => ({
              ...notice,
              unread: items.some((item) => item.id === notice.id) ? 1 : 0,
            })),
          next_offset: null,
        },
      });
    } else if (request.method() === "POST") {
      const { notice } = request.postDataJSON();
      previous = items;
      items = notice ? items.filter((item) => item.id !== notice.id) : [];
      await route.fulfill({
        json: { batch: "fixture", items, unread: items.length },
      });
    } else if (request.method() === "DELETE") {
      items = previous;
      await route.fulfill({ json: { items, unread: items.length } });
    } else {
      await route.fulfill({ json: { items, unread: items.length } });
    }
  });
  await page.addInitScript(
    (theme) => localStorage.setItem("theos-theme", theme),
    info.project.use.colorScheme,
  );
  await page.goto("/");
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#conversation-cost")).toContainText(
    "Conversation cost:",
  );
  const bell = page.getByRole("button", { name: "Notifications, 3 unread" });
  const transcript = page.getByRole("log", { name: "Conversation" });
  const inbox = page.locator("#notifications-view");
  const draft = page.locator("#message");
  const mobile = page.viewportSize().width <= 700;

  await expect(bell).toBeVisible();
  await expect(inbox).toBeHidden();
  await expect(transcript).not.toContainText("Workflow failed");
  await expect(page.locator("#sidebar")).toBeHidden();
  await draft.fill("Keep this draft");
  await bell.click();
  await expect(inbox).toBeVisible();
  await expect(transcript).toBeHidden();
  await expect(
    inbox.getByText("Workflow failed in sample/theos: Theos CI"),
  ).toHaveCount(1);
  await expect(inbox.getByRole("link", { name: "Run #1" })).toHaveAttribute(
    "href",
    notices[1].url,
  );
  const margins = await page.evaluate(() => {
    const panel = document
      .getElementById("notifications-view")
      .getBoundingClientRect();
    const content = document
      .querySelector(".notifications-page-content")
      .getBoundingClientRect();
    return [content.left - panel.left, panel.right - content.right];
  });
  expect(Math.abs(margins[0] - margins[1])).toBeLessThanOrEqual(2);
  expect(margins[0]).toBeGreaterThanOrEqual(mobile ? 14 : 20);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: info.outputPath("notifications-page.png") });

  await inbox
    .getByRole("button", { name: "Dismiss run #1", exact: true })
    .click();
  await expect(inbox.getByText("2 unread")).toBeVisible();
  await expect(inbox.getByRole("link", { name: "Run #1" })).toBeVisible();
  await expect(inbox.locator(".notification-state")).toHaveCount(1);
  await inbox.getByRole("button", { name: "Dismiss all" }).click();
  await inbox.getByRole("button", { name: "Unread", exact: true }).click();
  await expect(inbox.getByText("You’re all caught up.")).toBeVisible();
  await inbox.getByRole("button", { name: "Undo" }).click();
  await expect(inbox.getByText("2 unread")).toBeVisible();
  await expect(inbox.getByRole("link", { name: "Run #1" })).toBeHidden();

  await page.getByRole("button", { name: "Back to chat" }).click();
  await expect(inbox).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Notifications, 2 unread" }),
  ).toBeVisible();
  await expect(transcript).toBeVisible();
  await expect(draft).toHaveValue("Keep this draft");
});

test("the notifications page loads older saved alerts", async ({ page }) => {
  const path = "/api/notifications/browser";
  await page.route("**" + path + "**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/history")) {
      const older = url.searchParams.get("offset") === "50";
      return route.fulfill({
        json: {
          items: older
            ? [
                {
                  id: "oldest",
                  source: "reminder",
                  text: "Oldest saved alert",
                  created: 1794500000,
                  unread: 0,
                },
              ]
            : Array.from({ length: 50 }, (_, index) => ({
                id: "saved-" + index,
                source: "reminder",
                text: "Saved alert " + index,
                created: 1794630000 - index,
                unread: 0,
              })),
          next_offset: older ? null : 50,
        },
      });
    }
    return route.fulfill({ json: { items: [], unread: 0 } });
  });
  await page.goto("/");
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await page
    .getByRole("button", { name: "Notifications", exact: true })
    .click();
  const notifications = page.locator("#notifications-view");
  await expect(notifications.getByText("Saved alert 0")).toBeVisible();
  await expect(notifications.getByText("Oldest saved alert")).toHaveCount(0);
  await notifications.getByRole("button", { name: "Load older" }).click();
  await expect(notifications.getByText("Oldest saved alert")).toBeVisible();
  await expect(
    notifications.getByRole("button", { name: "Load older" }),
  ).toHaveCount(0);
});

test("the Focus sidebar toggles, switches theme, and opens a glass account menu", async ({
  page,
}, info) => {
  const initialTheme = info.project.use.colorScheme;
  const nextTheme = initialTheme === "dark" ? "light" : "dark";
  await page.goto("/");
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#conversation-cost")).toContainText(
    "Conversation cost:",
  );
  const mobile = page.viewportSize().width <= 700;
  const sidebar = page.locator("#sidebar");
  const toggle = page.locator("#toggle-sidebar");
  const account = page.locator("#account-menu");
  const draft = page.locator("#message");
  const chat = page.getByRole("log", { name: "Conversation" });
  const original = await chat.boundingBox();

  await expect(sidebar).toBeHidden();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await draft.fill("Keep this draft while the sidebar changes");
  await toggle.click();
  await expect(sidebar).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(sidebar).toHaveClass(/glass-surface/);
  await expect(sidebar.locator(":scope > .glass-optics")).toBeVisible();

  if (!mobile) {
    const expanded = await chat.boundingBox();
    const docked = await sidebar.boundingBox();
    expect(expanded.width).toBeLessThan(original.width);
    expect(expanded.x).toBeGreaterThanOrEqual(docked.x + docked.width - 1);
    await draft.click();
    await expect(sidebar).toBeVisible();
    await page.getByRole("button", { name: /^Notifications/ }).click();
    await expect(sidebar).toBeVisible();
    await page.getByRole("button", { name: "Back to chat" }).click();
    await expect(sidebar).toBeVisible();
  } else {
    await expect(page.locator("main")).toHaveAttribute("inert", "");
    const drawer = await sidebar.boundingBox();
    expect(drawer.x).toBeGreaterThanOrEqual(0);
    expect(drawer.width).toBeGreaterThan(200);
    expect(drawer.x + drawer.width).toBeLessThanOrEqual(
      page.viewportSize().width,
    );
  }

  await sidebar
    .getByRole("button", { name: `Switch to ${nextTheme} mode` })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", nextTheme);
  await expect(sidebar).toBeVisible();

  await page.locator("#account-button").click();
  await expect(account).toBeVisible();
  await expect(account).toHaveClass(/glass-surface/);
  await expect(account.locator(":scope > .glass-optics")).toBeVisible();
  await page.getByRole("button", { name: "Close account" }).click();
  await expect(account).toBeHidden();
  await expect(sidebar).toBeVisible();
  await expect(page.locator("#account-button")).toBeFocused();

  if (mobile)
    await sidebar
      .getByRole("button", { name: "Close recent conversations" })
      .click();
  else await toggle.click();
  await expect(sidebar).toBeHidden();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(draft).toHaveValue("Keep this draft while the sidebar changes");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", nextTheme);
  await expect(toggle).toBeVisible();
  await expect(sidebar).toBeHidden();
});
