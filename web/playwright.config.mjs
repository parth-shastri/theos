import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: process.env.THEOS_E2E_URL || "http://127.0.0.1:3000",
    reducedMotion: "reduce",
    launchOptions: process.env.THEOS_BROWSER_EXECUTABLE
      ? { executablePath: process.env.THEOS_BROWSER_EXECUTABLE }
      : {},
    trace: "retain-on-failure",
  },
  projects: [320, 390, 768, 1280].flatMap((width) =>
    ["light", "dark"].map((theme) => ({
      name: `${width}-${theme}`,
      use: { viewport: { width, height: 900 }, colorScheme: theme },
    })),
  ),
});
