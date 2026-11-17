import { expect, test } from "@playwright/test";

test("running responses stay with their conversation during navigation", async ({
  page,
}, info) => {
  const sessions = [
    { id: "first", title: "First conversation" },
    { id: "second", title: "Second conversation" },
  ];
  await page.route("**/api/**", (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/me")
      return route.fulfill({
        json: { id: "fixture", voice: {}, generation_capabilities: {} },
      });
    if (pathname === "/api/sessions") {
      if (route.request().method() === "POST") {
        const session = { id: "new", title: "New conversation" };
        sessions.push(session);
        return route.fulfill({ json: session });
      }
      return route.fulfill({ json: sessions });
    }
    const session = sessions.find(
      ({ id }) => pathname === "/api/sessions/" + id,
    );
    if (session)
      return route.fulfill({
        json: { ...session, history: [], approvals: [], usage: {} },
      });
    if (pathname === "/api/connections")
      return route.fulfill({ json: { accounts: [], services: [] } });
    if (pathname.endsWith("/tools")) return route.fulfill({ json: [] });
    return route.fulfill({ json: { items: [], unread: 0 } });
  });
  await page.addInitScript(() => {
    const fetch = window.fetch;
    const turns = new Map();
    window.responseNotifications = [];
    window.Notification = class {
      static permission = "default";
      static async requestPermission() {
        this.permission = "granted";
        return this.permission;
      }
      constructor(title, options) {
        window.responseNotifications.push({ title, tag: options.tag });
      }
    };
    window.finishTurn = (id, answer) => {
      const stream = turns.get(id);
      for (const event of [
        { type: "text", text: answer },
        { type: "assistant_complete", text: answer },
        { type: "done", status: "completed", duration_ms: 1000 },
      ]) {
        stream.enqueue(
          new TextEncoder().encode("data: " + JSON.stringify(event) + "\n\n"),
        );
      }
      stream.close();
    };
    window.fetch = (input, options) => {
      const match = String(input).match(/^\/api\/sessions\/([^/]+)\/turn$/);
      if (!match) return fetch(input, options);
      return Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              turns.set(match[1], controller);
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        ),
      );
    };
  });

  await page.goto("/");
  await expect(page.locator("#session-title")).toHaveText("First conversation");
  const input = page.locator("#message");
  const send = page.locator("#send");
  await input.fill("First prompt");
  await send.click();
  await expect(page.locator(".thinking-status .thinking-label")).toHaveText(
    "Thinking…",
  );
  await expect(send).toBeDisabled();

  const toggle = page.locator("#toggle-sidebar");
  const first = page.getByRole("button", { name: "First conversation" });
  const second = page
    .locator("#sessions")
    .getByRole("button", { name: "Second conversation" });
  const account = page.locator("#account-button");
  const closeSidebar = page.getByRole("button", {
    name: "Close recent conversations",
  });
  const mobile = page.viewportSize().width <= 700;
  await toggle.click();
  await expect(second).toBeEnabled();
  await account.click();
  const notificationToggle = page.getByRole("button", {
    name: "Response notifications",
    exact: true,
  });
  await expect(notificationToggle).toHaveAttribute("aria-pressed", "false");
  await notificationToggle.click();
  await expect(notificationToggle).toHaveAttribute("aria-pressed", "true");
  const tools = page.getByRole("button", { name: "Tools", exact: true });
  const back = page.getByRole("button", { name: "Back to chat" });
  const toolsView = page.locator("#tools-view");
  await tools.click();
  await expect(toolsView).toBeVisible();
  await back.click();
  if (mobile) await toggle.click();

  let releaseSelection;
  const heldSelection = new Promise((resolve) => {
    releaseSelection = resolve;
  });
  await page.route(
    "**/api/sessions/second",
    async (route) => {
      await heldSelection;
      await route.fallback();
    },
    { times: 1 },
  );
  const selectionStarted = page.waitForRequest("**/api/sessions/second");
  await second.click();
  await selectionStarted;
  if (mobile) await toggle.click();
  await account.click();
  await tools.click();
  await expect(toolsView).toBeVisible();
  const selectionResponse = page.waitForResponse("**/api/sessions/second");
  releaseSelection();
  await (await selectionResponse).finished();
  await back.click();
  await expect(page.locator("#session-title")).toHaveText("First conversation");
  if (mobile) await toggle.click();

  await second.click();
  await expect(page.locator("#session-title")).toHaveText(
    "Second conversation",
  );
  await expect(page.locator("#messages")).not.toContainText("First prompt");
  if (mobile) await toggle.click();
  await expect(second).toHaveAttribute("aria-current", "page");
  await expect(first).not.toHaveAttribute("aria-current");
  if (mobile) await closeSidebar.click();

  await input.fill("Second prompt");
  await send.click();
  await expect(page.locator(".thinking-status .thinking-label")).toHaveText(
    "Thinking…",
  );

  if (mobile) await toggle.click();
  await page.locator("#new-session").click();
  await expect(page.locator("#session-title")).toHaveText("New conversation");

  if (mobile) await toggle.click();
  await first.click();
  await expect(page.locator("#session-title")).toHaveText("First conversation");
  await expect(page.locator("#messages")).toContainText("First prompt");
  await expect(page.locator(".thinking-status .thinking-label")).toHaveText(
    "Thinking…",
  );
  await page.evaluate(() => window.finishTurn("second", "Second response"));
  if (mobile) await toggle.click();
  const unreadDot = second.locator(".conversation-unread-dot");
  await expect(unreadDot).toBeVisible();
  await expect(second).not.toHaveAttribute("aria-current");
  await expect(first).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#messages")).not.toContainText("Second response");
  await page.screenshot({
    path: info.outputPath("completed-background-chat.png"),
  });
  if (mobile) await closeSidebar.click();
  await page.evaluate(() => window.finishTurn("first", "First response"));
  await expect(page.locator("#messages")).toContainText("First response");
  await expect(send).toBeEnabled();

  if (mobile) await toggle.click();
  await second.click();
  await expect(page.locator("#messages")).toContainText("Second response");
  await expect(page.locator("#messages")).not.toContainText("First response");
  await expect(send).toBeEnabled();
  await expect(unreadDot).toHaveCount(0);
  if (mobile) await toggle.click();
  await account.click();
  await notificationToggle.click();
  await expect(notificationToggle).toHaveAttribute("aria-pressed", "false");
  await tools.click();
  await back.click();

  await input.fill("Follow-up prompt");
  await send.click();
  await expect(page.locator(".thinking-status .thinking-label")).toHaveText(
    "Thinking…",
  );
  if (mobile) await toggle.click();
  await account.click();
  await tools.click();
  await page.evaluate(() => window.finishTurn("second", "Follow-up response"));
  if (mobile) await toggle.click();
  await expect(unreadDot).toBeVisible();
  if (mobile) await closeSidebar.click();
  await back.click();
  await expect(unreadDot).toHaveCount(0);
  await expect(page.locator("#messages")).toContainText("Follow-up response");

  expect(await page.evaluate(() => window.responseNotifications)).toEqual([
    { title: "Theos response ready", tag: "theos-response-second" },
  ]);
});
