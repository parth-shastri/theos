import assert from "node:assert/strict";
import { test } from "node:test";
import {
  continueSignIn,
  prepareSignIn,
  signInUrl,
} from "../src/state/authorization.js";

test("sign-in reserves a window during the click and strips its opener", () => {
  const popup = {
    sessionStorage: { setItem() {} },
    document: { body: {} },
    opener: {},
    location: {
      replace(url) {
        this.url = url;
      },
    },
  };
  globalThis.window = {
    open: (url, target) => {
      assert.equal(url, "about:blank");
      assert.equal(target, "_blank");
      return popup;
    },
  };
  assert.equal(prepareSignIn(), popup);
  assert.equal(popup.opener, null);
  assert.equal(
    continueSignIn(popup, "https://accounts.example.test/sign-in?state=opaque"),
    true,
  );
  assert.equal(
    popup.location.url,
    "https://accounts.example.test/sign-in?state=opaque",
  );
  assert.equal(continueSignIn(null, "https://accounts.example.test"), false);
  assert.equal(
    continueSignIn({ ...popup, closed: true }, "https://accounts.example.test"),
    false,
  );
  globalThis.window = { open: () => null };
  assert.equal(prepareSignIn(), null);
  delete globalThis.window;
});

test("sign-in rejects unsafe redirects while preserving approved loopback returns", () => {
  for (const url of [
    "javascript:alert(1)",
    "data:text/html,hello",
    "http://accounts.example.test",
    "https://user:secret@example.test",
    "//example.test",
  ])
    assert.throws(() => signInUrl(url));
  assert.equal(
    signInUrl("http://localhost/callback?state=one"),
    "http://localhost/callback?state=one",
  );
  assert.equal(
    signInUrl("https://example.test/oauth"),
    "https://example.test/oauth",
  );
});
