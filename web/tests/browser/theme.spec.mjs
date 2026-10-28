import { test, expect } from "@playwright/test";

test("saved theme paints before React loads under the production CSP", async ({
  page,
}, info) => {
  const theme = info.project.use.colorScheme;
  await page.emulateMedia({ colorScheme: theme === "dark" ? "light" : "dark" });
  await page.addInitScript(
    (value) => localStorage.setItem("theos-theme", value),
    theme,
  );
  // Safari samples the backdrop before hydration. Keep React from loading.
  await page.route("**/_next/**/*.js", (route) => route.abort());
  const response = await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    theme === "dark" ? "rgb(14, 17, 22)" : "rgb(243, 245, 247)",
  );
  const nonce = await page
    .locator('script[src="/static/theme.js"]')
    .evaluate((script) => script.nonce);
  expect(nonce).toBeTruthy();
  expect(response.headers()["content-security-policy"]).toContain(
    `'nonce-${nonce}'`,
  );
});
