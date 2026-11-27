import { expect } from "@playwright/test";

export async function startChatting(page) {
  const skip = page.getByRole("button", {
    name: "Start chatting",
    exact: true,
  });
  if (await skip.isVisible()) {
    await skip.click();
    await expect(page.locator("#chat-setup-title")).toBeHidden();
  }
}
