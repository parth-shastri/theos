import { test, expect } from "@playwright/test";

const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";

async function signIn(page) {
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#workspace")).toBeVisible();
  await expect(page.locator("#conversation-cost")).toContainText(
    "Conversation cost:",
  );
}

async function navigate(page, id) {
  if (page.viewportSize().width <= 700) {
    await page.locator("#toggle-sidebar").click();
    await expect(page.locator("#sidebar")).toBeVisible();
  }
  await page.locator(`#${id}`).click();
}

async function noOverflow(page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}

test.beforeEach(async ({ page }, info) => {
  await page.addInitScript(
    (theme) => localStorage.setItem("theos-theme", theme),
    info.project.use.colorScheme,
  );
  await page.goto("/");
});

test("cookie sign-in, reload, CSRF rejection, streaming, and revocation", async ({
  page,
  context,
}) => {
  await expect(page.locator("#agent-name")).toHaveText(
    process.env.AGENT_NAME || "Theos",
  );
  await expect(page.locator("#agent-name > *")).toHaveCount(0);
  await expect(page).toHaveTitle(
    `${process.env.AGENT_NAME || "Theos"} / Personal assistant`,
  );
  const firstPolicy = (await page.request.get("/")).headers()[
    "content-security-policy"
  ];
  const secondPolicy = (await page.request.get("/")).headers()[
    "content-security-policy"
  ];
  expect(firstPolicy).toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
  expect(firstPolicy).not.toContain("'unsafe-inline'");
  expect(firstPolicy).not.toEqual(secondPolicy);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  expect((await page.request.get("/api/sessions")).status()).toBe(401);
  expect(
    (await page.request.post("/api/auth/login", { data: { token } })).status(),
  ).toBe(403);
  await signIn(page);
  expect(
    await page.evaluate(() => sessionStorage.getItem("theos-token")),
  ).toBeNull();
  const session = (await context.cookies()).find((cookie) =>
    cookie.name.endsWith("theos-session"),
  );
  expect(session.httpOnly).toBe(true);
  expect(session.sameSite).toBe("Strict");
  await page.reload();
  await expect(page.locator("#workspace")).toBeVisible();
  await expect(page.locator("#conversation-cost")).toContainText(
    "Conversation cost:",
  );
  await navigate(page, "new-session");
  await expect(page.locator("#message")).toBeFocused();
  await page
    .locator("#message")
    .fill("Hello from the Next.js acceptance check.");
  await page.locator("#message").press("Enter");
  await expect(page.locator("#messages .assistant")).toBeVisible();
  await expect(page.locator("#send")).toBeEnabled();
  await page.reload();
  await expect(page.locator("#messages")).toContainText(
    "Hello from the Next.js acceptance check.",
  );
  await navigate(page, "sign-out");
  await expect(page.locator("#login-form")).toBeVisible();
  expect((await page.request.get("/api/me")).status()).toBe(401);
  await context.addCookies([session]);
  expect((await page.request.get("/api/me")).status()).toBe(401);
  expect(errors).toEqual([]);
  await noOverflow(page);
});

test("composer, glass pickers, workspace panels, and mobile navigation", async ({
  page,
}) => {
  await signIn(page);
  const draft = "Preserve this draft while I inspect the workspace.";
  await page.locator("#message").fill(draft);
  await page.locator("#composer-add").click();
  await expect(page.locator("#composer-options")).toBeVisible();
  await noOverflow(page);
  await page.keyboard.press("Escape");
  await page.locator("#mode-trigger").click();
  await expect(page.locator("#mode-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await navigate(
    page,
    page.viewportSize().width <= 700
      ? "sidebar-settings-button"
      : "generation-button",
  );
  await expect(page.locator("#generation-dialog")).toBeVisible();
  await page.locator("#model-trigger").click();
  await expect(page.locator("#model-menu")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#generation-dialog")).toBeVisible();
  await page.locator("#generation-cancel").click();
  await expect(page.locator("#message")).toHaveValue(draft);
  for (const [button, panel, back] of [
    ["activity-button", "dashboard", "back-chat"],
    ["connections-button", "connections-view", "back-connections"],
    ["tools-button", "tools-view", "back-tools"],
    ["dashboard-button", "dashboard", "back-chat"],
  ]) {
    await navigate(page, button);
    await expect(page.locator(`#${panel}`)).toBeVisible();
    await noOverflow(page);
    await page.locator(`#${back}`).click();
  }
  await expect(page.locator("#message")).toHaveValue(draft);
  await page.locator("#message").fill("/usage");
  await page.locator("#send").click();
  await expect(page.locator("#usage-dialog")).toBeVisible();
  await page.locator("#usage-close").click();
  await noOverflow(page);
});
