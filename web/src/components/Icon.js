import { createElement as h } from "react";
import { iconPaths } from "../state/config.js";

export function Icon({ name, className }) {
  return h(
    "svg",
    {
      viewBox: "0 0 24 24",
      "aria-hidden": true,
      focusable: false,
      fill: name === "stop" ? "currentColor" : "none",
      stroke: "currentColor",
      strokeWidth: 1.8,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      className:
        className || (name === "loading" ? "voice-spinner" : undefined),
    },
    iconPaths[name].map((d) => h("path", { d, key: d })),
  );
}
