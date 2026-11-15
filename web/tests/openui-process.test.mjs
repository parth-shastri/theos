import { test } from "node:test";
import assert from "node:assert/strict";
import { processStepIcon } from "../src/openui/process-icons.js";
import { iconPaths } from "../src/state/config.js";

test("saved process steps get distinct icons from their roles", () => {
  const steps = [
    {
      label: "Establish trust",
      description: "A certifying authority issues a certificate.",
      icon: "connection",
    },
    {
      label: "Sign the exact file",
      description: "Use the private key to sign its hash.",
      icon: "connection",
    },
    {
      label: "Check the signature",
      description: "Use the public key to verify the signature.",
      icon: "connection",
    },
  ];
  const icons = steps.map(processStepIcon);
  assert.deepEqual(icons, ["certificate", "signature", "verify"]);
  for (const icon of icons) assert.ok(iconPaths[icon]?.length);
});

test("process steps respect a meaningful supplied icon", () => {
  assert.equal(
    processStepIcon({
      label: "Check the server",
      description: "The browser checks a secure connection.",
      icon: "lock",
    }),
    "lock",
  );
  assert.equal(
    processStepIcon({ label: "Connect", description: "Open a connection." }),
    null,
  );
});
