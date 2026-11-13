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
  const session = await page.request.post("/api/sessions", {
    headers: { Origin: new URL(page.url()).origin, "X-Theos-Request": "1" },
    data: { title: "Activity preview" },
  });
  expect(session.ok()).toBe(true);
  const { id } = await session.json();
  const sessionPath = `/api/sessions/${id}`;
  const saved = await (await page.request.get(sessionPath)).json();
  await page.reload();
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
  const activity = page.locator("#messages .turn-activity");
  const indicator = activity.locator(".thinking-status");
  await expect(indicator).toHaveText("Thinking…");
  await expect(activity.locator("li")).toHaveCount(0);
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
  const call = {
    id: "calendar",
    name: "calendar_list_events",
    arguments: { calendar_id: "primary" },
  };
  for (const event of [
    {
      type: "reasoning",
      text: "I’ll check tomorrow’s calendar for a 30-minute opening.",
    },
    {
      type: "assistant_complete",
      requested_tools: [call.name],
      tool_calls: [call],
    },
    { type: "tool", call_id: call.id, name: call.name, status: "running" },
    {
      type: "tool",
      call_id: call.id,
      name: call.name,
      status: "completed",
      content: "One meeting ends at 11:30 AM.",
    },
    { type: "thinking" },
    { type: "reasoning", text: "The half hour after the meeting is free." },
  ]) {
    await emit(event);
    if (event.type === "tool")
      await expect(activity.locator(".tool-activity summary")).toHaveText(
        event.status === "running"
          ? "Reading calendar events"
          : "Read calendar events",
      );
    await expect(page.locator("#messages .thinking-orb")).toHaveCount(1);
    await expect(page.locator("#status")).toBeEmpty();
  }
  const rows = activity.locator(".turn-activity-rows > li");
  await expect(rows).toHaveCount(3);
  await expect(rows.first()).toHaveText(
    "I’ll check tomorrow’s calendar for a 30-minute opening.",
  );
  await expect(rows.nth(1).locator("summary")).toHaveText(
    "Read calendar events",
  );
  await expect(rows.last()).toHaveText(
    "The half hour after the meeting is free.",
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(indicator.locator(".thinking-label")).toHaveCSS(
    "animation-name",
    "none",
  );
  await expect(orb).toHaveCSS("animation-name", "none");
  await page
    .locator("#chat-view")
    .screenshot({ path: info.outputPath("ongoing-turn.png") });
  const answer = "You’re free tomorrow from 11:30 AM to noon.";
  await emit({ type: "text", text: answer });
  await emit({ type: "assistant_complete", text: answer });
  await expect(indicator).toBeVisible();
  await emit({ type: "done", status: "completed", duration_ms: 8000 });
  await expect(indicator).toHaveCount(0);
  await page.evaluate(() => window.turnFixture.close());
  await expect(send).toBeEnabled();
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#messages .assistant").last()).toContainText(
    answer,
  );
  const summary = activity.locator(":scope > summary");
  await expect(summary).toHaveText("Thought for 8 s");
  await expect(rows.first()).toBeHidden();
  await summary.click();
  const tool = activity.locator(".tool-activity");
  await expect(tool.locator(".tool-result")).toBeHidden();
  await tool.locator("summary").click();
  await expect(tool.locator(".tool-inputs")).toContainText(
    '"calendar_id": "primary"',
  );
  await expect(tool.locator(".tool-result")).toHaveText(
    "One meeting ends at 11:30 AM.",
  );
  await page
    .locator("#chat-view")
    .screenshot({ path: info.outputPath("expanded-turn.png") });
  await page.route(`**${sessionPath}`, (route) =>
    route.fulfill({
      json: {
        ...saved,
        history: [
          {
            type: "user",
            content: "Synthetic activity check",
            display: { turn_activity: { duration_ms: 8000 } },
          },
          {
            type: "assistant",
            reasoning:
              "I’ll check tomorrow’s calendar for a 30-minute opening.",
            tool_calls: [call],
          },
          {
            type: "tool_result",
            name: call.name,
            call_id: call.id,
            status: "completed",
            content: "One meeting ends at 11:30 AM.",
          },
          {
            type: "assistant",
            reasoning: "The half hour after the meeting is free.",
            text: answer,
          },
        ],
      },
    }),
  );
  await page.reload();
  await expect(summary).toHaveText("Thought for 8 s");
  await expect(rows.first()).toBeHidden();
  await summary.click();
  await expect(rows).toHaveCount(3);
  await expect(tool.locator("summary")).toHaveText("Read calendar events");
  await expect(page.locator("#messages .thinking-orb")).toHaveCount(0);
});
