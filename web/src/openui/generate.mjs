import { readFile, mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createParser } from "@openuidev/lang-core";
import {
  openuiLibrary,
  openuiPromptOptions,
  OPENUI_LIBRARY_VERSION,
} from "./library.js";

const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const packageData = JSON.parse(
  await readFile(resolve(repository, "web/package.json"), "utf8"),
);
const output = resolve(repository, "src/theos/prompts/openui");
const schema = openuiLibrary.toJSONSchema();
for (const example of openuiPromptOptions.examples) {
  const { root, meta } = createParser(schema, "TheosAnswer").parse(example);
  if (
    !root ||
    meta.incomplete ||
    meta.errors.length ||
    meta.unresolved.length ||
    meta.orphaned.length
  )
    throw new Error("Invalid OpenUI prompt example:\n" + example);
}
const files = new Map([
  ["system-prompt.md", openuiLibrary.prompt(openuiPromptOptions).trim() + "\n"],
  ["library-schema.json", JSON.stringify(schema, null, 2) + "\n"],
  [
    "manifest.json",
    JSON.stringify(
      {
        library_version: OPENUI_LIBRARY_VERSION,
        renderer_package: "@openuidev/react-lang",
        renderer_version: packageData.dependencies["@openuidev/react-lang"],
        schema_package: "zod",
        schema_version: packageData.dependencies.zod,
      },
      null,
      2,
    ) + "\n",
  ],
]);

if (process.argv.includes("--check")) {
  let mismatch = false;
  for (const [name, expected] of files) {
    try {
      const actual = await readFile(resolve(output, name), "utf8");
      if (actual !== expected) {
        console.error(`Generated OpenUI artifact differs: ${name}`);
        mismatch = true;
      }
    } catch {
      console.error(`Generated OpenUI artifact is missing: ${name}`);
      mismatch = true;
    }
  }
  if (mismatch) process.exitCode = 1;
} else {
  await mkdir(output, { recursive: true });
  for (const [name, contents] of files) {
    await writeFile(resolve(output, name), contents);
  }
}
