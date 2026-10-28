import { createElement as h, useState } from "react";

function LogoImage({ url }) {
  const [failed, setFailed] = useState(false);
  return failed
    ? null
    : h("img", {
        src: url,
        alt: "",
        width: 22,
        height: 22,
        loading: "lazy",
        decoding: "async",
        referrerPolicy: "no-referrer",
        onError: () => setFailed(true),
      });
}
export function SourceLogo({ source, url }) {
  return h("span", { className: "openui-source-mark", "aria-hidden": true }, [
    h("span", { key: "initial" }, source?.initial || "?"),
    source && url ? h(LogoImage, { key: url, url }) : null,
  ]);
}
export function SourcePreview({ url, source, title, alt }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return h(
    "a",
    {
      className: "openui-result-preview",
      href: source.href,
      target: "_blank",
      rel: "noopener noreferrer",
      "aria-label": `View source: ${title}`,
    },
    h("img", {
      src: url,
      alt: alt || `Image from ${title}`,
      loading: "lazy",
      decoding: "async",
      referrerPolicy: "no-referrer",
      onError: () => setFailed(true),
    }),
  );
}
