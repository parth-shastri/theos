"use client";
import { createElement, memo, useEffect, useMemo, useState } from "react";
import { Marked } from "marked";
import createDOMPurify from "dompurify";

const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
const parser = new Marked({
  gfm: true,
  breaks: false,
  renderer: {
    html: ({ text }) => escape(text),
    image: ({ href, text }) =>
      '<a href="' + escape(href) + '">Image: ' + escape(text) + "</a>",
  },
});
let sanitizer;
function fragment(source) {
  sanitizer ||= createDOMPurify(window);
  return sanitizer.sanitize(parser.parse(source), {
    RETURN_DOM_FRAGMENT: true,
    ALLOWED_TAGS: [
      "p",
      "br",
      "h1",
      "h2",
      "h3",
      "h4",
      "h5",
      "h6",
      "pre",
      "code",
      "ul",
      "ol",
      "li",
      "blockquote",
      "strong",
      "em",
      "del",
      "a",
      "hr",
      "table",
      "thead",
      "tbody",
      "tr",
      "th",
      "td",
      "input",
    ],
    ALLOWED_ATTR: [
      "href",
      "title",
      "class",
      "type",
      "checked",
      "disabled",
      "start",
      "align",
    ],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
  });
}
function CodeBlock({ code, language, children }) {
  const [copied, setCopied] = useState("");
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(""), 1600);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <div className="code-block">
      <div className="code-toolbar">
        <span>{language || "Code"}</span>
        <button
          type="button"
          className="copy-code"
          aria-label={
            copied === "Copied"
              ? "Code copied"
              : copied
                ? "Copy failed. Select the code and copy it manually."
                : "Copy code"
          }
          title={
            copied === "Copy failed"
              ? "Select the code and copy it manually."
              : undefined
          }
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(code);
              setCopied("Copied");
            } catch {
              setCopied("Copy failed");
            }
          }}
        >
          {copied || "Copy"}
        </button>
      </div>
      {children}
    </div>
  );
}
function convert(node, key) {
  if (node.nodeType === 3) return node.textContent;
  if (node.nodeType !== 1) return null;
  const tag = node.tagName.toLowerCase();
  const props = { key };
  for (const { name, value } of node.attributes) {
    if (name === "class") props.className = value;
    else if (!["checked", "disabled", "type"].includes(name))
      props[name] = value;
  }
  if (tag === "a" && props.href) {
    try {
      const url = new URL(props.href, location.href);
      if (!["http:", "https:", "mailto:"].includes(url.protocol))
        delete props.href;
      else {
        props.target = "_blank";
        props.rel = "noopener noreferrer";
      }
    } catch {
      delete props.href;
    }
  }
  if (tag === "input")
    return createElement("input", {
      ...props,
      type: "checkbox",
      disabled: true,
      defaultChecked: node.hasAttribute("checked"),
    });
  const children = [...node.childNodes].map((child, index) =>
    convert(child, key + "-" + index),
  );
  const element = createElement(tag, props, ...children);
  if (tag === "table")
    return (
      <div
        className="markdown-table"
        tabIndex={0}
        role="region"
        aria-label="Markdown table"
        key={key}
      >
        {element}
      </div>
    );
  if (tag === "pre" && node.querySelector("code")) {
    const code = node.querySelector("code");
    return (
      <CodeBlock
        code={code.textContent}
        language={code.className.replace(/^language-/, "")}
        key={key}
      >
        {element}
      </CodeBlock>
    );
  }
  return element;
}
export function markdownText(source) {
  if (!source || typeof window === "undefined") return "";
  return fragment(source).textContent.trim();
}
const Markdown = memo(function Markdown({
  source = "",
  className = "",
  hidden,
  ...props
}) {
  const content = useMemo(
    () =>
      typeof window === "undefined"
        ? null
        : [...fragment(source).childNodes].map((node, index) =>
            convert(node, String(index)),
          ),
    [source],
  );
  return (
    <div
      {...props}
      className={(className + " markdown").trim()}
      hidden={hidden}
    >
      {content}
    </div>
  );
});
export default Markdown;
