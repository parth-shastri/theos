import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "node:http";
import { forwardToBackend } from "../src/server/backend.js";

const received = [];
const upstream = createServer((request, response) => {
  let body = "";
  request.on("data", (chunk) => (body += chunk));
  request.on("end", () => {
    received.push({ url: request.url, headers: request.headers, body });
    if (request.url === "/api/stream") {
      response.writeHead(200, { "Content-Type": "text/event-stream" });
      response.write('data: {"type":"text","text":"first"}\n\n');
      setTimeout(() => response.end('data: {"type":"done"}\n\n'), 80);
    } else {
      response.writeHead(200, {
        "Content-Type": "application/json",
        "Set-Cookie": [
          "theos-session=opaque; HttpOnly; SameSite=Strict; Path=/",
          "theos-pairing=pair; HttpOnly; Path=/api/onboarding",
        ],
      });
      response.end('{"ok":true}');
    }
  });
});
await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
process.env.THEOS_API_URL = `http://127.0.0.1:${upstream.address().port}`;
process.env.AGENT_WEB_URL = "https://theos.test";
process.env.THEOS_FRONTEND_SECRET = "private-service-secret-" + "s".repeat(32);
after(() => new Promise((resolve) => upstream.close(resolve)));

const request = (path, options = {}) =>
  new Request("https://theos.test" + path, options);

test("proxy validates the browser origin before forwarding mutations", async () => {
  for (const headers of [
    {},
    { Origin: "https://evil.test", "X-Theos-Request": "1" },
    { Origin: "https://theos.test" },
  ]) {
    const result = await forwardToBackend(
      request("/api/auth/login", { method: "POST", headers, body: "{}" }),
      "/api/auth/login",
    );
    assert.equal(result.status, 403);
  }
  assert.equal(received.length, 0);
});

test("proxy limits forwarded credentials, streams bodies, and retains separate cookies", async () => {
  const result = await forwardToBackend(
    request("/api/auth/login?test=1", {
      method: "POST",
      headers: {
        Origin: "https://theos.test",
        "X-Theos-Request": "1",
        "Content-Type": "application/json",
        Cookie: "theos-session=opaque; tracking=private",
        Authorization: "Bearer must-not-forward",
        "X-Theos-Frontend-Secret": "forged",
      },
      body: '{"token":"private-login-token"}',
    }),
    "/api/auth/login",
  );
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("cache-control"), "no-store");
  assert.equal(result.headers.getSetCookie().length, 2);
  const sent = received.at(-1);
  assert.equal(sent.url, "/api/auth/login?test=1");
  assert.equal(sent.headers.cookie, "theos-session=opaque");
  assert.equal(sent.headers.authorization, undefined);
  assert.equal(
    sent.headers["x-theos-frontend-secret"],
    process.env.THEOS_FRONTEND_SECRET,
  );
  assert.equal(sent.body, '{"token":"private-login-token"}');
  await result.text();
});

test("SSE forwards the first event before the upstream response finishes", async () => {
  const result = await forwardToBackend(request("/api/stream"), "/api/stream");
  assert.equal(result.headers.get("x-accel-buffering"), "no");
  const reader = result.body.getReader();
  const first = new TextDecoder().decode((await reader.read()).value);
  assert.match(first, /first/);
  assert.doesNotMatch(first, /done/);
  let remaining = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    remaining += new TextDecoder().decode(chunk.value);
  }
  assert.match(remaining, /done/);
});

test("client addresses are accepted only from the explicitly trusted ingress header", async () => {
  const forged = await forwardToBackend(
    request("/api/me", { headers: { "X-Theos-Client-IP": "203.0.113.99" } }),
    "/api/me",
  );
  await forged.text();
  assert.equal(received.at(-1).headers["x-theos-client-ip"], undefined);
  process.env.THEOS_CLIENT_IP_HEADER = "cf-connecting-ip";
  try {
    const result = await forwardToBackend(
      request("/api/me", {
        headers: {
          "CF-Connecting-IP": "203.0.113.10",
          "X-Theos-Client-IP": "203.0.113.99",
        },
      }),
      "/api/me",
    );
    await result.text();
    assert.equal(received.at(-1).headers["x-theos-client-ip"], "203.0.113.10");
  } finally {
    delete process.env.THEOS_CLIENT_IP_HEADER;
  }
});
