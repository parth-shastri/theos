import { test } from "node:test";
import assert from "node:assert/strict";
import {
  searchPresentation,
  sourcePresentation,
  excerptText,
  referenceLabel,
} from "../src/openui/evidence.js";

test("search labels remove operator syntax while preserving the exact query and constraints", () => {
  const query =
    'site:openui.com/examples "LangGraph Platform" "Vercel AI SDK" -site:spam.example filetype:md OpenUI integration';
  const shown = searchPresentation(query);
  assert.equal(shown.original, query);
  assert.equal(
    shown.terms,
    "LangGraph Platform Vercel AI SDK OpenUI integration",
  );
  assert.deepEqual(shown.sites, ["openui.com/examples"]);
  assert.deepEqual(shown.excludedSites, ["spam.example"]);
  assert.deepEqual(shown.formats, ["MD"]);
  assert.equal(searchPresentation('site:"docs.example.com"').terms, "");
});
test("source metadata uses safe public links without credentials or fabricated reference IDs", () => {
  assert.equal(sourcePresentation("javascript:alert(1)"), null);
  assert.equal(sourcePresentation("https://user:secret@example.com"), null);
  assert.deepEqual(
    sourcePresentation("https://www.openui.com/examples?utm_source=test"),
    {
      href: "https://www.openui.com/examples?utm_source=test",
      host: "openui.com",
      path: "/examples",
      initial: "O",
    },
  );
  assert.equal(
    referenceLabel(
      "https://www.openui.com/examples",
      "https://www.openui.com/examples",
    ),
    "",
  );
  assert.equal(referenceLabel("source-12", "https://example.com"), "source-12");
  assert.equal(
    excerptText("Excerpt: “A documented integration.”"),
    "“A documented integration.”",
  );
});

test("search images use only the same-origin image route", async () => {
  const { imagePresentation } = await import("../src/openui/evidence.js");
  assert.equal(
    imagePresentation("https://images.example.com/a.png?q=one&size=2"),
    "/api/search-image?url=https%3A%2F%2Fimages.example.com%2Fa.png%3Fq%3Done%26size%3D2",
  );
  for (const url of [
    "javascript:alert(1)",
    "data:image/png,abc",
    "https://user:pass@example.com/x",
    null,
  ])
    assert.equal(imagePresentation(url), null);
});

test("missing logos discover icons only from the source site", async () => {
  const { logoPresentation, imagePresentation } = await import(
    "../src/openui/evidence.js"
  );
  assert.equal(
    logoPresentation("", "https://science.nasa.gov/path/page?q=private"),
    "/api/search-image?site=https%3A%2F%2Fscience.nasa.gov",
  );
  assert.equal(
    logoPresentation(
      "https://cdn.example.com/logo.png",
      "https://example.com/page",
    ),
    imagePresentation("https://cdn.example.com/logo.png"),
  );
  assert.equal(logoPresentation("", "javascript:bad"), null);
});
