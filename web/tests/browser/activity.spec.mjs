import { test, expect } from "@playwright/test";

test("turn feedback stays in the conversation through tools and final text", async ({
  page,
}, info) => {
  const token =
    process.env.THEOS_E2E_TOKEN || "nextjs-browser-preview-token-123456789";
  await page.goto("/");
  await page.locator("#token").fill(token);
  await page.locator("#login-form button[type=submit]").click();
  await expect(page.locator("#conversation-cost")).toContainText(
    "Conversation cost:",
  );
  // Feed real SSE frames through the client reader without cross-origin fixture requests.
  await page.evaluate(() => {
    const original = window.fetch;
    window.fetch = (input, options) => {
      if (String(input).endsWith("/turn") && options?.method === "POST") {
        return Promise.resolve(
          new Response(
            new ReadableStream({
              start(controller) {
                window.turnFixture = {
                  emit(event) {
                    controller.enqueue(
                      new TextEncoder().encode(
                        "data: " + JSON.stringify(event) + "\n\n",
                      ),
                    );
                  },
                  close() {
                    controller.close();
                  },
                };
              },
            }),
            { headers: { "Content-Type": "text/event-stream" } },
          ),
        );
      }
      return original(input, options);
    };
  });
  const emit = (event) =>
    page.evaluate((value) => window.turnFixture.emit(value), event);
  await page.locator("#message").fill("Synthetic activity check");
  const send = page.locator("#send");
  await expect(send).toHaveCSS("background-color", "rgb(41, 189, 134)");
  await expect(send).toHaveCSS("color", "rgb(11, 31, 22)");
  await send.hover();
  await expect(send).toHaveCSS("background-color", "rgb(34, 169, 118)");
  await send.click();
  const bubble = page.locator(".message.user .body").last();
  await expect(bubble).toHaveCSS("background-color", "rgb(41, 189, 134)");
  await expect(bubble).toHaveCSS("color", "rgb(11, 31, 22)");
  const indicator = page.locator(
    "#messages .turn-activity, #messages .thinking.is-thinking",
  );
  await expect(indicator).toHaveText("Thinking…");
  await expect(page.locator("#status")).toBeEmpty();
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(indicator.locator(".thinking-label")).toHaveCSS(
    "animation-name",
    "thinking-pulse",
  );
  const orb = indicator.locator(".thinking-orb");
  await expect(orb).toHaveCSS("animation-name", "none");
  await expect(orb).toHaveCSS("box-shadow", "none");
  await expect(orb).toHaveCSS(
    "background-image",
    /radial-gradient.*rgb\(212, 233, 107\).*rgb\(41, 189, 134\)/,
  );
  for (const event of [
    { type: "reasoning", text: "Check the source." },
    {
      type: "assistant_complete",
      reasoning: "Check the source.",
      requested_tools: ["search"],
    },
    { type: "tool", call_id: "search", name: "search", status: "started" },
    {
      type: "tool",
      call_id: "search",
      name: "search",
      status: "completed",
      content: "Source found",
    },
    { type: "thinking" },
    { type: "text", text: "Answer text" },
    { type: "assistant_complete", text: "Answer text" },
  ]) {
    await emit(event);
    if (event.type === "reasoning") {
      await expect(
        page.locator(".thinking.is-thinking .thinking-label"),
      ).toHaveText("Thinking…");
      await expect(page.locator(".turn-activity")).toHaveCount(0);
    }
    if (event.type === "tool")
      await expect(page.locator(".tool-activity summary").last()).toHaveText(
        "search · " + event.status,
      );
    await expect(indicator).toHaveCount(1);
    await expect(indicator).toBeVisible();
    await expect(page.locator("#status")).toBeEmpty();
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(indicator.locator(".thinking-label")).toHaveCSS(
    "animation-name",
    "none",
  );
  await expect(orb).toHaveCSS("animation-name", "none");
  await page
    .locator("#chat-view")
    .screenshot({ path: info.outputPath("ongoing-turn.png") });
  await emit({ type: "done", status: "completed" });
  await expect(indicator).toHaveCount(0);
  await page.evaluate(() => window.turnFixture.close());
  await expect(send).toBeEnabled();
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#messages")).toContainText("Answer text");
});
