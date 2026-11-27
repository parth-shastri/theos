import { test, expect } from "@playwright/test";

const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";
async function fixture(page, { onboarding = false, name = "Ada" } = {}) {
  const data = {
    accounts: ["gmail", "calendar", "zepto", "health", "slack", "github"].map(
      (id) => ({
        id,
        name: {
          gmail: "Gmail",
          calendar: "Google Calendar",
          zepto: "Zepto",
          health: "Google Health",
          slack: "Slack",
          github: "GitHub",
        }[id],
        configured: true,
        connected: false,
        setup: { status: "idle" },
      }),
    ),
    services: [],
    onboarding: {
      needed: onboarding,
      display_name: name,
      timezone: "Asia/Kolkata",
    },
  };
  const journey = {
    needed: onboarding,
    step: onboarding ? "name" : "ready",
    revision: 0,
    display_name: name,
    timezone: "Asia/Kolkata",
    pending_task: "",
  };
  const state = { data, profile: null, turns: 0, journey };
  await page.route("**/api/me", async (route) => {
    const response = await route.fetch();
    if (!response.ok()) return route.fulfill({ response });
    await route.fulfill({ json: { ...(await response.json()), journey } });
  });
  await page.route("**/api/journey", async (route) => {
    if (route.request().method() === "POST") {
      const { action, value } = route.request().postDataJSON();
      if (action === "reply") {
        journey.candidate = value;
        journey.step = "confirm_name";
      }
      if (action === "confirm") {
        journey.display_name = journey.candidate;
        journey.step = "timezone";
      }
      if (action === "skip" || action === "finish") {
        journey.needed = false;
        journey.step = "ready";
      }
      state.profile = {
        display_name: journey.display_name,
        timezone: journey.timezone,
      };
      journey.revision++;
    }
    await route.fulfill({ json: journey });
  });
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
  // Startup loads the selected conversation before finishing sign-in. Wait for
  // completion so its navigation cannot race this fixture's Connections click.
  await expect(page.locator("#login-form button[type=submit]")).toBeEnabled();
  if (!onboarding) {
    if (page.viewportSize().width <= 700)
      await page.locator("#toggle-sidebar").click();
    await page.locator("#account-button").click();
    await page.locator("#connections-button").click();
  }
  await expect(
    page.locator(onboarding ? "#chat-view" : "#connections-view"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  return state;
}

test("onboarding stays in chat, confirms a name, and can skip accounts", async ({
  page,
}, info) => {
  const state = await fixture(page, { onboarding: true, name: "" });
  await expect(
    page.getByRole("heading", { name: "What should I call you?" }),
  ).toBeVisible();
  await expect(page.locator("#connections-view")).toBeHidden();
  await page.locator("#message").fill("Ada L.");
  await page.locator("#send").click();
  await expect(
    page.getByRole("heading", { name: "Shall I call you Ada L.?" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Yes, save it" }).click();
  await expect(
    page.getByRole("heading", { name: "Which timezone should I use?" }),
  ).toBeVisible();
  await page
    .locator("#chat-view")
    .screenshot({ path: info.outputPath("chat-onboarding.png") });
  await page.getByRole("button", { name: "Skip for now", exact: true }).click();
  await expect(page.locator("#chat-setup-title")).toBeHidden();
  await expect(page.locator("#chat-view")).toBeVisible();
  expect(state.profile).toEqual({
    display_name: "Ada L.",
    timezone: "Asia/Kolkata",
  });
  expect(state.data.accounts.every((account) => !account.connected)).toBe(true);
  expect(state.turns).toBe(0);
  expect(await page.context().pages()).toHaveLength(1);
});

test("account setup opens in chat and retains the originating conversation", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.locator("#back-connections").click();
  let destination;
  const account = state.data.accounts.find((account) => account.id === "gmail");
  await page.route("**/api/connections/gmail/connect", async (route) => {
    destination = route.request().postDataJSON();
    account.setup = {
      status: "waiting",
      url: "https://accounts.example.test/gmail",
    };
    await route.fulfill({ json: account.setup });
  });
  await page.locator("#message").fill("Connect Gmail");
  await page.locator("#send").click();
  await expect(page.locator("#connections-view")).toBeHidden();
  const card = page.locator('.chat-account-setup [data-account="gmail"]');
  await expect(card).toBeVisible();
  const opened = page.waitForEvent("popup");
  await card.getByRole("button", { name: "Connect", exact: true }).click();
  const popup = await opened;
  await expect(popup).toHaveURL("https://accounts.example.test/gmail");
  expect(destination.source).toBe("chat");
  expect(destination.session_id).toMatch(/^[a-f0-9]{32}$/);
  account.connected = true;
  account.setup = { status: "connected" };
  await popup
    .goto(
      new URL(
        `/?conversation=${destination.session_id}&connected=gmail`,
        page.url(),
      ).href,
    )
    .catch((error) => {
      if (!popup.isClosed()) throw error;
    });
  await expect.poll(() => popup.isClosed()).toBe(true);
  await expect(card.getByText("Connected", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Continue chatting", exact: true })
    .click();
  await expect(page.locator(".chat-account-setup")).toHaveCount(0);
  expect(state.turns).toBe(0);
});

for (const service of ["gmail", "calendar", "slack", "github"]) {
  test(`Connect opens ${service} sign-in automatically and cancellation preserves the previous account`, async ({
    page,
  }) => {
    const state = await fixture(page);
    const account = state.data.accounts.find(
      (account) => account.id === service,
    );
    account.connected = true;
    await page.route(`**/api/connections/${service}/connect`, async (route) => {
      account.setup = { status: "waiting" };
      await route.fulfill({
        json: {
          status: "waiting",
          url: `https://accounts.example.test/${service}`,
        },
      });
    });
    await page.route(`**/api/connections/${service}/cancel`, async (route) => {
      account.setup = { status: "cancelled", message: "Sign-in cancelled." };
      await route.fulfill({ json: { cancelled: true } });
    });
    await page.locator("#refresh-connections").click();
    const card = page.locator(`[data-account="${service}"]`);
    const opened = page.waitForEvent("popup");
    await card.getByRole("button", { name: "Reconnect", exact: true }).click();
    const popup = await opened;
    await expect(popup).toHaveURL(`https://accounts.example.test/${service}`);
    await expect(
      card.getByText("Awaiting sign-in", { exact: true }),
    ).toBeVisible();
    await card
      .getByRole("button", { name: "Cancel setup", exact: true })
      .click();
    await expect(card.getByText("Connected", { exact: true })).toBeVisible();
    expect(account.connected).toBe(true);
    await popup.close();
    const nextOpened = page.waitForEvent("popup");
    await card.getByRole("button", { name: "Reconnect", exact: true }).click();
    const nextPopup = await nextOpened;
    await expect(nextPopup).toHaveURL(
      `https://accounts.example.test/${service}`,
    );
    account.setup = { status: "connected" };
    await nextPopup
      .goto(new URL("/?connections=1", page.url()).href)
      .catch((error) => {
        if (!nextPopup.isClosed()) throw error;
      });
    await expect.poll(() => nextPopup.isClosed()).toBe(true);
    expect(state.turns).toBe(0);
  });
}

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
  const state = await fixture(page);
  await expect(
    page.getByRole("heading", { name: "Connections", exact: true }),
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
  await page.locator("#back-connections").click();
  await expect(page.locator("#chat-view")).toBeVisible();
  expect(state.profile).toBeNull();
  await page.goto("/?connections=1");
  await expect(page.locator("#connections-view")).toBeVisible();
  await expect(page).not.toHaveURL(/connections=1/);
  expect(state.turns).toBe(0);
});

test("browser sign-in keeps private input outside chat and supports clearing the profile", async ({
  page,
}, info) => {
  const state = await fixture(page);
  state.data.services.push({
    id: "sandbox",
    name: "Sandbox",
    configured: true,
  });
  await page.locator("#refresh-connections").click();
  const actions = [];
  const login = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#f5f6f4"/><rect x="400" y="130" width="480" height="400" rx="20" fill="white"/><text x="450" y="200" font-family="sans-serif" font-size="28" fill="#183b30">Sign in to your account</text><rect x="450" y="240" width="380" height="48" rx="8" fill="#edf0ed"/><rect x="450" y="310" width="380" height="48" rx="8" fill="#edf0ed"/><rect x="450" y="390" width="380" height="48" rx="8" fill="#27694f"/><text x="590" y="421" font-family="sans-serif" font-size="20" fill="white">Continue</text></svg>`;
  await page.route("**/api/connections/browser/action", async (route) => {
    actions.push(route.request().postDataJSON());
    await route.fulfill({
      json: {
        success: true,
        image: `data:image/svg+xml;base64,${Buffer.from(login).toString("base64")}`,
        snapshot: {
          snapshot: "- textbox Username\n- textbox Password\n- button Continue",
        },
      },
    });
  });
  let cleared = false;
  await page.route("**/api/connections/browser/disconnect", async (route) => {
    cleared = true;
    await route.fulfill({ json: { disconnected: true } });
  });
  const card = page.locator(".browser-sign-in");
  await card.getByRole("button", { name: "Open browser", exact: true }).click();
  await card.getByLabel("Website address").fill("https://login.example.test");
  await card.getByRole("button", { name: "Go", exact: true }).click();
  await expect(card.locator(".browser-screen")).toBeVisible();
  await card.getByLabel("Private input").fill("test-password-never-in-chat");
  await card
    .getByRole("button", { name: "Type into page", exact: true })
    .click();
  await expect(card.getByLabel("Private input")).toHaveValue("");
  await expect(
    card.getByRole("button", { name: "Next field", exact: true }),
  ).toBeEnabled();
  await card.getByRole("button", { name: "Next field", exact: true }).click();
  await expect
    .poll(() => actions.at(-1))
    .toEqual({ action: "press", key: "Tab" });
  expect(actions[1]).toEqual({
    action: "type",
    text: "test-password-never-in-chat",
  });
  expect(state.turns).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await card.screenshot({ path: info.outputPath("browser-sign-in.png") });
  await card
    .getByRole("button", { name: "Clear saved browser login", exact: true })
    .click();
  await expect(card.getByText("Saved browser login cleared.")).toBeVisible();
  await expect(card.locator(".browser-screen")).toHaveCount(0);
  expect(cleared).toBe(true);
});

test("GitHub settings link to the separate notifications page without model turns", async ({
  page,
}, info) => {
  const state = await fixture(page);
  const account = state.data.accounts.find((item) => item.id === "github");
  account.connected = true;
  account.notifications = {
    available: true,
    enabled: false,
    telegram: false,
    telegram_available: false,
    items: [],
  };
  await page.route("**/api/connections/github/notifications", async (route) => {
    Object.assign(account.notifications, route.request().postDataJSON());
    await route.fulfill({ json: account.notifications });
  });
  await page.locator("#refresh-connections").click();
  const card = page.locator('[data-account="github"]');
  await card.getByLabel("Notify me in Theos", { exact: true }).check();
  await expect(
    card.getByLabel("Notify me in Theos", { exact: true }),
  ).toBeChecked();
  await expect(
    card.getByLabel("Also notify my private Telegram chat"),
  ).toBeDisabled();
  account.notifications.items.push({
    id: "notice-one",
    text: "Review requested in sample/project #12: Fix <script>",
    url: "https://github.com/sample/project/pull/12",
    created: 1794630600,
    read: false,
    telegram: "not_requested",
  });
  await page.route("**/api/notifications/browser/history**", (route) =>
    route.fulfill({
      json: {
        items: account.notifications.items.map((item) => ({
          ...item,
          source: "github",
          unread: 1,
        })),
        next_offset: null,
      },
    }),
  );
  await page.route("**/api/notifications/browser", (route) =>
    route.fulfill({
      json: {
        items: account.notifications.items.map((item) => ({
          ...item,
          source: "github",
        })),
        unread: 1,
      },
    }),
  );
  await page.locator("#refresh-connections").click();
  await expect(card.getByText(/Fix <script>/)).toHaveCount(0);
  await expect(card.locator(".github-notification-inbox")).toHaveCount(0);
  await card.screenshot({
    path: info.outputPath("github-notification-settings.png"),
  });
  await card.getByLabel("Notify me in Theos", { exact: true }).uncheck();
  await expect(
    card.getByLabel("Notify me in Theos", { exact: true }),
  ).not.toBeChecked();
  await card.getByRole("button", { name: "View all notifications" }).click();
  await expect(page.locator("#notifications-view")).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Review requested/ }),
  ).toHaveAttribute("href", "https://github.com/sample/project/pull/12");
  await page.locator("#notifications-view").screenshot({
    path: info.outputPath("notifications-page-from-github.png"),
  });
  expect(state.turns).toBe(0);
});

test("Telegram calling onboarding verifies, tests, saves preferences, and disconnects without a model turn", async ({
  page,
}, info) => {
  const state = await fixture(page);
  state.data.calling = {
    configured: true,
    status: "disconnected",
    reminders: false,
    approvals: false,
  };
  let calls = 0;
  await page.route("**/api/calling/*", async (route) => {
    const step = route.request().url().split("/").pop();
    const calling = state.data.calling;
    if (step === "connect")
      Object.assign(calling, {
        status: "waiting",
        url: "https://t.me/theos_test?text=proof",
      });
    if (step === "test") {
      calls++;
      calling.test_status = "pending";
    }
    if (step === "confirm")
      Object.assign(calling, {
        status: "ready",
        ...route.request().postDataJSON(),
      });
    if (step === "preferences")
      Object.assign(calling, route.request().postDataJSON());
    if (step === "disconnect")
      Object.assign(calling, {
        status: "disabled",
        reminders: false,
        approvals: false,
      });
    await route.fulfill({ json: calling });
  });
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  const setup = page.getByRole("region", { name: "Telegram calls" });
  await expect(setup).toBeVisible();
  await setup
    .getByRole("button", { name: "Connect Telegram calls", exact: true })
    .click();
  await expect(
    setup.getByRole("link", { name: "Open Theos calling" }),
  ).toHaveAttribute("href", "https://t.me/theos_test?text=proof");
  state.data.calling.status = "linked";
  await setup.getByRole("button", { name: "Check connection" }).click();
  await setup.getByRole("button", { name: "Call me for the test" }).click();
  await expect(
    setup.getByRole("button", { name: /I heard the message/ }),
  ).toBeDisabled();
  state.data.calling.test_status = "completed";
  await expect(
    setup.getByRole("button", { name: /I heard the message/ }),
  ).toBeEnabled();
  await setup
    .getByLabel("Call when an approval waits for two minutes")
    .uncheck();
  await expect(setup.getByLabel("Call for reminders")).not.toBeChecked();
  await setup.getByLabel("Call for reminders").check();
  await setup.screenshot({ path: info.outputPath("calling-onboarding.png") });
  await setup.getByRole("button", { name: /I heard the message/ }).click();
  await expect(setup.getByText("Connected", { exact: true })).toBeVisible();
  expect(state.data.calling.reminders).toBe(true);
  expect(state.data.calling.approvals).toBe(false);
  await setup.getByLabel("Call for reminders").uncheck();
  await expect.poll(() => state.data.calling.reminders).toBe(false);
  await setup.getByRole("button", { name: "Disconnect calls" }).click();
  await expect(
    setup.getByRole("button", { name: "Connect Telegram calls", exact: true }),
  ).toBeVisible();
  expect(calls).toBe(1);
  expect(state.turns).toBe(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
