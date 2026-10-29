import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "node:http";
import { forwardGitHubWebhook } from "../src/server/github-webhook.js";
import { forwardToBackend } from "../src/server/backend.js";

const received = [];
const server = createServer((req, res) => {
  const parts = [];
  req.on("data", (part) => parts.push(part));
  req.on("end", () => {
    received.push({
      url: req.url,
      headers: req.headers,
      body: Buffer.concat(parts),
    });
    res.writeHead(202, {
      "Content-Type": "application/json",
      "Set-Cookie": "tracking=must-not-forward",
    });
    res.end('{"accepted":true}');
  });
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
process.env.THEOS_API_URL = `http://127.0.0.1:${server.address().port}`;
process.env.AGENT_WEB_URL = "https://theos.test";
process.env.THEOS_FRONTEND_SECRET = "s".repeat(48);
after(() => new Promise((resolve) => server.close(resolve)));

test("the dedicated webhook proxy preserves exact bytes without browser credentials or CSRF bypasses elsewhere", async () => {
  const body = '{ "title": "café", "spaces":  true }\n';
  const result = await forwardGitHubWebhook(
    new Request("https://theos.test/webhooks/github?discard=1", {
      method: "POST",
      body,
      headers: {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": "sha256=signature",
        "X-GitHub-Delivery": "delivery",
        "X-GitHub-Event": "issues",
        Cookie: "theos-session=private",
        Authorization: "Bearer private",
        "X-Theos-Frontend-Secret": "forged",
      },
    }),
  );
  assert.equal(result.status, 202);
  await result.text();
  const sent = received.at(-1);
  assert.equal(sent.url, "/webhooks/github");
  assert.deepEqual(sent.body, Buffer.from(body));
  assert.equal(sent.headers["x-hub-signature-256"], "sha256=signature");
  for (const name of ["cookie", "authorization", "x-theos-frontend-secret"])
    assert.equal(sent.headers[name], undefined);
  assert.equal(result.headers.get("set-cookie"), null);
  assert.equal(result.headers.get("cache-control"), "no-store");
  const count = received.length;
  assert.equal(
    (
      await forwardToBackend(
        new Request("https://theos.test/api/auth/login", {
          method: "POST",
          body: "{}",
        }),
        "/api/auth/login",
      )
    ).status,
    403,
  );
  assert.equal(received.length, count);
});

test("webhook body limits measure actual bytes even without a trustworthy Content-Length", async () => {
  const before = received.length;
  const result = await forwardGitHubWebhook(
    new Request("https://theos.test/webhooks/github", {
      method: "POST",
      headers: { "Content-Length": "1" },
      body: "x".repeat(1024 * 1024 + 1),
    }),
  );
  assert.equal(result.status, 413);
  assert.equal(received.length, before);
});
