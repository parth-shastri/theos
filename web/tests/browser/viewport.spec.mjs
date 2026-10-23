import { test, expect } from "@playwright/test";

const token =
  process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";

test.beforeEach(async ({ page }, info) => {
  test.skip(page.viewportSize().width > 700, "Mobile keyboard behavior");
  await page.addInitScript((theme) => {
    localStorage.setItem("theos-theme", theme);
    // Model iOS: the keyboard changes the visual viewport, not the layout viewport.
    const viewport = new EventTarget();
    Object.assign(viewport, {
      height: innerHeight,
      width: innerWidth,
      offsetTop: 0,
      offsetLeft: 0,
      scale: 1,
    });
    Object.defineProperty(window, "visualViewport", { value: viewport });
  }, info.project.use.colorScheme);
  await page.goto("/");
});

async function viewport(page, values, event = "resize") {
  await page.evaluate(
    ({ values, event }) => {
      Object.assign(window.visualViewport, values);
      window.visualViewport.dispatchEvent(new Event(event));
    },
    { values, event },
  );
}

async function insideViewport(page, selector, top, height) {
  await expect
    .poll(async () => {
      const box = await page.locator(selector).boundingBox();
      return (
        !!box && box.y >= top - 1 && box.y + box.height <= top + height + 1
      );
    })
    .toBe(true);
}

async function signIn(page) {
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#workspace")).toBeVisible();
  await expect(page.locator("#conversation-cost")).toContainText(
    "Conversation cost:",
  );
}

async function composerAboveKeyboard(page, top, height) {
  await insideViewport(page, "#composer", top, height);
  await expect
    .poll(async () => {
      const box = await page.locator("#composer").boundingBox();
      return top + height - box.y - box.height;
    })
    .toBeLessThanOrEqual(24);
}

test("keyboard resize and pan keep the composer and navigation in view", async ({
  page,
}, info) => {
  await signIn(page);
  const input = page.locator("#message");
  const draft = Array.from(
    { length: 12 },
    (_, i) => `Draft line ${i + 1}`,
  ).join("\n");
  await input.fill(draft);
  await viewport(page, { height: 420, offsetTop: 0 });
  await composerAboveKeyboard(page, 0, 420);
  await insideViewport(page, "#send", 0, 420);

  // Focus can move the viewport without changing its height.
  await viewport(page, { offsetTop: 96 }, "scroll");
  await composerAboveKeyboard(page, 96, 420);
  await expect
    .poll(async () => (await page.locator(".app-viewport").boundingBox()).y)
    .toBe(96);
  await insideViewport(page, "#toggle-sidebar", 96, 420);
  await expect(input).toHaveValue(draft);
  await expect(input).toBeFocused();
  await page
    .locator(".app-viewport")
    .screenshot({ path: info.outputPath("keyboard-open.png") });

  await page.locator("#toggle-sidebar").click();
  await insideViewport(page, "#sidebar", 96, 420);
  await page.locator("#sidebar-settings-button").click();
  await insideViewport(page, "#generation-dialog", 96, 420);
  await page.locator("#generation-cancel").click();

  // Keyboard dismissal may restore height before Safari clears its old offset.
  await viewport(page, { height: page.viewportSize().height });
  await expect
    .poll(async () => (await page.locator(".app-viewport").boundingBox()).y)
    .toBe(0);
  await insideViewport(page, "#composer", 0, page.viewportSize().height);
  await expect(input).toHaveValue(draft);
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBe(
    page.viewportSize().height,
  );

  const fullSize = await page.locator(".app-viewport").boundingBox();
  await viewport(page, { height: 300, offsetTop: 120, scale: 2 });
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  expect(await page.locator(".app-viewport").boundingBox()).toEqual(fullSize);
  await viewport(page, { height: 420, offsetTop: 64, scale: 1 });
  await composerAboveKeyboard(page, 64, 420);
});

test("token sign-in remains reachable above the keyboard", async ({ page }) => {
  await page.locator("#token").focus();
  await viewport(page, { height: 360, offsetTop: 72 });
  await expect
    .poll(async () => (await page.locator("#login").boundingBox()).y)
    .toBe(72);
  await page
    .locator("#login-form button[type=submit]")
    .scrollIntoViewIfNeeded();
  await insideViewport(page, "#login-form button[type=submit]", 72, 360);
  await signIn(page);
  await composerAboveKeyboard(page, 72, 360);
});

test("repeated keyboard toggles recover from incomplete measurements and page restoration", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await signIn(page);
  const input = page.locator("#message");
  await input.fill("Keep this draft through keyboard toggles");
  for (const height of [420, 300, 420]) {
    await viewport(page, { height, offsetTop: 80 });
    await composerAboveKeyboard(page, 80, height);
    const box = await page.locator(".app-viewport").boundingBox();
    await viewport(page, { height: 0 });
    await expect(page.locator("#composer")).toBeVisible();
    await expect
      .poll(
        async () => (await page.locator(".app-viewport").boundingBox()).height,
      )
      .toBe(box.height);
    // Returning from the page cache can restore dimensions without a resize event.
    await page.evaluate(() => {
      Object.assign(visualViewport, { height: innerHeight, offsetTop: 80 });
      dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    await insideViewport(page, "#composer", 0, page.viewportSize().height);
    await expect
      .poll(async () => (await page.locator(".app-viewport").boundingBox()).y)
      .toBe(0);
    await expect(input).toHaveValue("Keep this draft through keyboard toggles");
  }
});
