import { test } from "node:test";
import assert from "node:assert/strict";
import {
  imageURL,
  publicImageAddress,
  publicImageLookup,
  downloadImage,
} from "../src/server/search-images.js";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
  "base64",
);

test("image fetching blocks private addresses, alternate IP encodings, credentials, ports, and mixed DNS answers", async () => {
  for (const address of [
    "127.0.0.1",
    "10.1.2.3",
    "100.64.0.1",
    "169.254.169.254",
    "172.16.0.1",
    "192.168.1.1",
    "::1",
    "::ffff:127.0.0.1",
    "fe80::1",
    "2001:db8::1",
    "2002:7f00:1::",
  ])
    assert.equal(publicImageAddress(address), false, address);
  for (const value of [
    "http://2130706433/x",
    "http://0x7f000001/x",
    "http://[::ffff:127.0.0.1]/x",
    "https://user:pass@example.com/x",
    "https://example.com:8080/x",
    "file:///tmp/x",
    "data:image/png,hi",
    "http://service.internal/x",
    "http://localhost/x",
  ])
    assert.throws(() => imageURL(value), undefined, value);
  assert.equal(publicImageAddress("8.8.8.8"), true);
  assert.equal(publicImageAddress("2606:4700:4700::1111"), true);
  await new Promise((resolve) =>
    publicImageLookup(
      "example.com",
      {},
      (error) => {
        assert.match(error.message, /not public/);
        resolve();
      },
      async () => [
        { address: "8.8.8.8", family: 4 },
        { address: "127.0.0.1", family: 4 },
      ],
    ),
  );
  await new Promise((resolve) =>
    publicImageLookup(
      "example.com",
      { all: true },
      (error, records) => {
        assert.equal(error, null);
        assert.deepEqual(records, [{ address: "8.8.8.8", family: 4 }]);
        resolve();
      },
      async () => [{ address: "8.8.8.8", family: 4 }],
    ),
  );
});

test("image downloads validate every redirect and bound bodies without forwarding credentials", async () => {
  const seen = [];
  const image = await downloadImage("https://example.com/photo", {
    fetch: async (url, options) => {
      seen.push({ url: url.href, options });
      return seen.length === 1
        ? new Response(null, {
            status: 302,
            headers: { location: "/actual.png" },
          })
        : new Response(png);
    },
  });
  assert.equal(image.type, "image/png");
  assert.deepEqual(image.bytes, png);
  assert.equal(seen[1].url, "https://example.com/actual.png");
  assert.equal(seen[1].options.headers.Cookie, undefined);
  assert.equal(seen[1].options.headers.Authorization, undefined);
  assert.equal(seen[1].options.headers.Referer, undefined);
  await assert.rejects(
    downloadImage("https://example.com/x", {
      fetch: async () =>
        new Response(null, {
          status: 302,
          headers: { location: "http://127.0.0.1/private" },
        }),
    }),
  );
  for (const body of [
    "<svg onload='alert(1)'/>",
    "<html>not an image</html>",
    Buffer.alloc(2 * 1024 * 1024 + 1),
  ]) {
    await assert.rejects(
      downloadImage("https://example.com/x", {
        fetch: async () =>
          new Response(body, { headers: { "content-type": "image/png" } }),
      }),
    );
  }
  await assert.rejects(
    downloadImage("https://example.com/x", {
      fetch: async () =>
        new Response(png, { headers: { "content-length": "999999999" } }),
    }),
  );
});

test("logo discovery reads a bounded source head, prefers declared raster icons, and never executes page markup", async () => {
  const { iconCandidates, downloadLogo } = await import(
    "../src/server/search-images.js"
  );
  const html = `<html><head>
    <script>throw new Error('never execute')</script>
    <link rel="stylesheet" href="/not-an-icon.png">
    <link rel="icon" type="image/svg+xml" href="/icon.svg">
    <link rel="icon" href="http://127.0.0.1/private.png">
    <link rel="apple-touch-icon" sizes="180x180" href="/touch.png">
    <link REL='icon' sizes='64x64' href='/logo.png?x=1&amp;y=2'>
    </head><body>ignored</body></html>`;
  assert.deepEqual(iconCandidates(html, "https://example.com/"), [
    "https://example.com/logo.png?x=1&y=2",
    "https://example.com/touch.png",
  ]);
  const seen = [];
  const result = await downloadLogo(
    "https://example.com/article?private-query",
    {
      fetch: async (url) => {
        seen.push(url.href);
        return seen.length === 1
          ? new Response(html, { headers: { "content-type": "text/html" } })
          : new Response(png);
      },
    },
  );
  assert.equal(result.type, "image/png");
  assert.deepEqual(seen, [
    "https://example.com/",
    "https://example.com/logo.png?x=1&y=2",
  ]);
  const fallback = [];
  await downloadLogo("https://example.com/", {
    fetch: async (url) => {
      fallback.push(url.href);
      return fallback.length === 1
        ? new Response("unavailable", { status: 403 })
        : new Response(png);
    },
  });
  assert.deepEqual(fallback, [
    "https://example.com/",
    "https://example.com/favicon.ico",
  ]);
});
