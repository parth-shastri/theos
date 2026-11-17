import { expect, test } from "@playwright/test";

test("voice waveform reacts to audio and preserves transcription review", async ({
  page,
}, info) => {
  const sessions = [
    { id: "first", title: "Voice preview" },
    { id: "second", title: "Another conversation" },
  ];
  let releaseTranscription;
  let uploads = 0;
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/me")
      return route.fulfill({
        json: {
          id: "fixture",
          voice: { transcription: true, max_upload_bytes: 10_000_000 },
          generation_capabilities: {},
        },
      });
    if (pathname === "/api/sessions") return route.fulfill({ json: sessions });
    const session = sessions.find(
      ({ id }) => pathname === "/api/sessions/" + id,
    );
    if (session)
      return route.fulfill({
        json: { ...session, history: [], approvals: [], usage: {} },
      });
    if (pathname === "/api/connections")
      return route.fulfill({ json: { accounts: [], services: [] } });
    if (pathname === "/api/files") {
      expect(route.request().postDataBuffer()?.length).toBeGreaterThan(0);
      uploads++;
      return route.fulfill({ json: { id: "voice-file" } });
    }
    if (pathname === "/api/audio/transcribe") {
      expect(route.request().postDataJSON()).toEqual({ file_id: "voice-file" });
      const transcript = await new Promise((resolve) => {
        releaseTranscription = resolve;
      });
      return route.fulfill({ json: { text: transcript } });
    }
    return route.fulfill({ json: { items: [], unread: 0 } });
  });
  await page.addInitScript(() => {
    // Use real Web Audio and MediaRecorder without a physical microphone.
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new AudioContext();
      const output = context.createMediaStreamDestination();
      const signal = context.createOscillator();
      const gain = context.createGain();
      const now = context.currentTime;
      gain.gain.setValueAtTime(0, now);
      gain.gain.setValueAtTime(0.14, now + 0.12);
      gain.gain.setValueAtTime(0.03, now + 0.45);
      gain.gain.setValueAtTime(0.2, now + 0.7);
      signal.connect(gain).connect(output);
      signal.start();
      await context.resume();
      window.fixtureStream = output.stream;
      return output.stream;
    };
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/");
  const input = page.locator("#message");
  const waveform = page.locator(".composer-waveform");
  const record = page.getByRole("button", { name: "Record a voice message" });
  await input.fill("Existing draft.");
  await record.click();
  await expect(waveform).toBeVisible();
  await expect(input).toBeHidden();
  await expect(page.locator("#status")).toHaveText("Listening...");
  const signalWidth = () =>
    waveform.locator("canvas").evaluate((canvas) => {
      const { width, height } = canvas;
      if (!width || !height) return 0;
      const pixels = canvas
        .getContext("2d")
        .getImageData(0, Math.floor(height / 2), width, 1);
      return pixels.data.filter((value, index) => index % 4 === 3 && value > 0)
        .length;
    });
  await expect.poll(signalWidth).toBeGreaterThan(24);
  await page
    .locator("#composer")
    .screenshot({ path: info.outputPath("voice-waveform.png") });
  const requested = page.waitForRequest("**/api/audio/transcribe");
  await page.getByRole("button", { name: "Stop voice recording" }).click();
  await requested;
  await expect(waveform).toBeVisible();
  await expect(page.locator("#status")).toHaveText("Transcribing...");
  await expect(waveform).toHaveCSS("animation-name", "composer-waveform-pulse");
  await expect.poll(() => Boolean(releaseTranscription)).toBe(true);
  releaseTranscription("A reviewed transcript.");
  await expect(waveform).toBeHidden();
  await expect(input).toHaveValue("Existing draft.\nA reviewed transcript.");
  await expect(input).toBeFocused();
  expect(uploads).toBe(1);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await record.click();
  await expect(waveform).toBeVisible();
  await expect(waveform).toHaveCSS("animation-name", "none");
  expect(await signalWidth()).toBe(0);
  await page.getByRole("button", { name: "Cancel recording" }).click();
  await expect(waveform).toBeHidden();
  await expect(record).toBeEnabled();
  await expect(input).toHaveValue("Existing draft.\nA reviewed transcript.");
  expect(uploads).toBe(1);
  expect(
    await page.evaluate(() =>
      window.fixtureStream
        .getTracks()
        .every((track) => track.readyState === "ended"),
    ),
  ).toBe(true);

  await record.click();
  await expect(waveform).toBeVisible();
  const sidebar = page.locator("#toggle-sidebar");
  const first = page.getByRole("button", { name: "Voice preview" });
  const second = page.getByRole("button", { name: "Another conversation" });
  const mobile = page.viewportSize().width <= 700;
  await sidebar.click();
  await second.click();
  await expect(page.locator("#session-title")).toHaveText(
    "Another conversation",
  );
  await expect(waveform).toBeHidden();
  await expect(record).toBeEnabled();
  expect(uploads).toBe(1);

  await record.click();
  await expect(waveform).toBeVisible();
  releaseTranscription = undefined;
  await page.getByRole("button", { name: "Stop voice recording" }).click();
  await expect.poll(() => Boolean(releaseTranscription)).toBe(true);
  if (mobile) await sidebar.click();
  await first.click();
  await expect(page.locator("#session-title")).toHaveText("Voice preview");
  await expect(waveform).toBeHidden();
  releaseTranscription("Discard this transcript.");
  await expect(input).toHaveValue("Existing draft.\nA reviewed transcript.");
  expect(uploads).toBe(2);
});
