import { test, expect } from "@playwright/test";

const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";
async function fixture(page, { onboarding = false, name = "Ada" } = {}) {
  const data = {
    accounts: ["gmail", "zepto", "health"].map((id) => ({
      id,
      name: { gmail: "Gmail", zepto: "Zepto", health: "Google Health" }[id],
      configured: true,
      connected: false,
      setup: { status: "idle" },
    })),
    services: [],
    onboarding: {
      needed: onboarding,
      display_name: name,
      timezone: "Asia/Kolkata",
    },
  };
  const state = { data, profile: null, turns: 0 };
  page.on("request", (request) => {
    if (request.url().endsWith("/turn")) state.turns++;
  });
  await page.context().route("https://accounts.example.test/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<title>Private sign-in fixture</title><p>Complete sign-in</p>",
    }),
  );
  await page
    .context()
    .route("**/api/connections", (route) => route.fulfill({ json: data }));
  await page.route("**/api/connections/onboarding", async (route) => {
    state.profile = route.request().postDataJSON();
    data.onboarding.needed = false;
    Object.assign(data.onboarding, state.profile);
    await route.fulfill({
      json: {
        display_name: data.onboarding.display_name,
        timezone: data.onboarding.timezone,
      },
    });
  });
  await page.goto("/");
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#workspace")).toBeVisible();
  if (!onboarding) {
    if (page.viewportSize().width <= 700)
      await page.locator("#toggle-sidebar").click();
    await page.locator("#connections-button").click();
  }
  await expect(page.locator("#connections-view")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  return state;
}

test("optional onboarding saves a preferred name and returns to chat without signing in to accounts", async ({
  page,
}, info) => {
  const state = await fixture(page, { onboarding: true, name: "" });
  await expect(
    page.getByRole("heading", { name: "What should I call you?" }),
  ).toBeVisible();
  await page.locator("#setup-name").fill("Ada L.");
  await page
    .locator("#connections-view")
    .screenshot({ path: info.outputPath("connection-onboarding.png") });
  await page
    .getByRole("button", { name: "Continue to chat", exact: true })
    .click();
  await expect(page.locator("#chat-view")).toBeVisible();
  expect(state.profile).toEqual({
    display_name: "Ada L.",
    timezone: "Asia/Kolkata",
  });
  expect(state.data.accounts.every((account) => !account.connected)).toBe(true);
  expect(state.turns).toBe(0);
  expect(await page.context().pages()).toHaveLength(1);
});

test("Connect opens Google sign-in automatically and cancellation preserves the previous account", async ({
  page,
}) => {
  const state = await fixture(page);
  const account = state.data.accounts[0];
  account.connected = true;
  await page.route("**/api/connections/gmail/connect", async (route) => {
    account.setup = { status: "waiting" };
    await route.fulfill({
      json: { status: "waiting", url: "https://accounts.example.test/google" },
    });
  });
  await page.route("**/api/connections/gmail/cancel", async (route) => {
    account.setup = { status: "cancelled", message: "Sign-in cancelled." };
    await route.fulfill({ json: { cancelled: true } });
  });
  await page.locator("#refresh-connections").click();
  const card = page.locator('[data-account="gmail"]');
  const opened = page.waitForEvent("popup");
  await card.getByRole("button", { name: "Reconnect", exact: true }).click();
  const popup = await opened;
  await expect(popup).toHaveURL("https://accounts.example.test/google");
  await expect(
    card.getByText("Awaiting sign-in", { exact: true }),
  ).toBeVisible();
  await card.getByRole("button", { name: "Cancel setup", exact: true }).click();
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  expect(account.connected).toBe(true);
  await popup.close();
  const nextOpened = page.waitForEvent("popup");
  await card.getByRole("button", { name: "Reconnect", exact: true }).click();
  const nextPopup = await nextOpened;
  await expect(nextPopup).toHaveURL("https://accounts.example.test/google");
  account.setup = { status: "connected" };
  await nextPopup
    .goto(new URL("/?connections=1", page.url()).href)
    .catch((error) => {
      if (!nextPopup.isClosed()) throw error;
    });
  await expect.poll(() => nextPopup.isClosed()).toBe(true);
  expect(state.turns).toBe(0);
});

test("Zepto opens its discovered link and verifies the private return before reporting success", async ({
  page,
}, info) => {
  const state = await fixture(page);
  const account = state.data.accounts.find((account) => account.id === "zepto");
  let returned;
  await page.route("**/api/connections/zepto/connect", async (route) => {
    account.setup = { status: "starting" };
    await route.fulfill({ json: { status: "starting" } });
    account.setup = {
      status: "waiting",
      url: "https://accounts.example.test/zepto",
      manual_return: true,
    };
  });
  await page.route("**/api/connections/zepto/finish", async (route) => {
    returned = route.request().postDataJSON();
    account.setup = {
      status: "waiting",
      manual_return: true,
      message: "Checking account access.",
    };
    await route.fulfill({ json: { accepted: true } });
  });
  const card = page.locator('[data-account="zepto"]');
  const opened = page.waitForEvent("popup");
  await card.getByRole("button", { name: "Connect", exact: true }).click();
  const popup = await opened;
  await expect(popup).toHaveURL("https://accounts.example.test/zepto");
  const returnLink =
    "http://localhost/callback?state=fixture-state&code=fixture-code";
  await page.locator("#zepto-return-url").fill(returnLink);
  await card.screenshot({ path: info.outputPath("zepto-handoff.png") });
  await card
    .getByRole("button", { name: "Finish connection", exact: true })
    .click();
  expect(returned).toEqual({ url: returnLink });
  await expect(card.getByText("Connected", { exact: true })).not.toBeVisible();
  account.connected = true;
  account.setup = { status: "connected", message: "Zepto is connected." };
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  await card.getByRole("button", { name: "Choose a delivery address" }).click();
  await expect(page.locator("#message")).toHaveValue(
    "Help me choose a saved Zepto delivery address before shopping.",
  );
  expect(state.turns).toBe(0);
});

test("blocked popups retain an explicit sign-in link and callbacks return to Connections", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.open = () => null;
  });
  const state = await fixture(page, { onboarding: true });
  await expect(
    page.getByRole("heading", { name: "Welcome, Ada" }),
  ).toBeVisible();
  await expect(page.locator("#setup-name")).toHaveCount(0);
  await page.route("**/api/connections/health/connect", async (route) => {
    state.data.accounts.find((account) => account.id === "health").setup = {
      status: "waiting",
    };
    await route.fulfill({
      json: { status: "waiting", url: "https://accounts.example.test/health" },
    });
  });
  const card = page.locator('[data-account="health"]');
  await card.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(
    card.getByRole("link", { name: "Open sign-in" }),
  ).toHaveAttribute("href", "https://accounts.example.test/health");
  await expect(card.getByText(/If sign-in did not open/)).toBeVisible();
  await page.getByRole("button", { name: "Skip for now", exact: true }).click();
  await expect(page.locator("#chat-view")).toBeVisible();
  expect(state.profile).toEqual({});
  await page.goto("/?connections=1");
  await expect(page.locator("#connections-view")).toBeVisible();
  await expect(page).not.toHaveURL(/connections=1/);
  expect(state.turns).toBe(0);
});
