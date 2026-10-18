"use strict";
// Pinned browser libraries are recorded in browser-vendor-provenance.json.
window.TheosMarkdown = (() => {
  const sources = new WeakMap();
  const frames = new WeakMap();
  const rendered = new WeakMap();
  const escape = (text) =>
    String(text).replace(
      /[&<>"']/g,
      (character) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[character],
    );
  const parser = new marked.Marked({
    gfm: true,
    breaks: false,
    renderer: {
      html({ text }) {
        return escape(text);
      },
      // Display image links without loading remote assets from model output.
      image({ href, text }) {
        return `<a href="${escape(href)}">Image: ${escape(text)}</a>`;
      },
    },
  });

  function draw(element, source) {
    if (rendered.get(element) === source) return;
    const fragment = DOMPurify.sanitize(parser.parse(source), {
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
    for (const link of fragment.querySelectorAll("a")) {
      const href = link.getAttribute("href");
      if (!href) continue;
      try {
        const url = new URL(href, location.href);
        if (!["http:", "https:", "mailto:"].includes(url.protocol)) {
          link.removeAttribute("href");
          continue;
        }
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      } catch (_) {
        link.removeAttribute("href");
      }
    }
    for (const input of fragment.querySelectorAll("input")) {
      input.type = "checkbox";
      input.disabled = true;
    }
    for (const table of fragment.querySelectorAll("table")) {
      const scroll = document.createElement("div");
      scroll.className = "markdown-table";
      scroll.tabIndex = 0;
      scroll.setAttribute("role", "region");
      scroll.setAttribute("aria-label", "Markdown table");
      table.replaceWith(scroll);
      scroll.append(table);
    }
    for (const pre of fragment.querySelectorAll("pre")) {
      const code = pre.querySelector("code");
      if (!code) continue;
      const block = document.createElement("div");
      block.className = "code-block";
      const toolbar = document.createElement("div");
      toolbar.className = "code-toolbar";
      const language = document.createElement("span");
      language.textContent = code.className.replace(/^language-/, "") || "Code";
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "copy-code";
      copy.textContent = "Copy";
      copy.setAttribute("aria-label", "Copy code");
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText(code.textContent);
          copy.textContent = "Copied";
          copy.setAttribute("aria-label", "Code copied");
        } catch (_) {
          copy.textContent = "Copy failed";
          copy.setAttribute(
            "aria-label",
            "Copy failed. Select the code and copy it manually.",
          );
          copy.title = "Select the code and copy it manually.";
        }
        setTimeout(() => {
          copy.textContent = "Copy";
          copy.setAttribute("aria-label", "Copy code");
        }, 1600);
      };
      toolbar.append(language, copy);
      pre.replaceWith(block);
      block.append(toolbar, pre);
    }
    element.replaceChildren(fragment);
    rendered.set(element, source);
  }

  function render(element, source = "", streaming = false) {
    sources.set(element, source);
    element.classList.add("markdown");
    if (frames.has(element)) cancelAnimationFrame(frames.get(element));
    frames.delete(element);
    if (!streaming) return draw(element, source);
    frames.set(
      element,
      requestAnimationFrame(() => {
        frames.delete(element);
        if (element.isConnected) {
          draw(element, sources.get(element));
          element.dispatchEvent(
            new Event("markdown-rendered", { bubbles: true }),
          );
        }
      }),
    );
  }
  function text(element) {
    const copy = element.cloneNode(true);
    copy
      .querySelectorAll(".code-toolbar")
      .forEach((toolbar) => toolbar.remove());
    return copy.textContent.trim();
  }
  return {
    render,
    text,
    source: (element) => sources.get(element) ?? element.textContent,
  };
})();
