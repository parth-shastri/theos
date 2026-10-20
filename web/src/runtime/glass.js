// Keep optical effects separate from chat state and provider behavior.
export function createGlass(scope) {
  if (
    !CSS.supports("backdrop-filter", "blur(1px)") &&
    !CSS.supports("-webkit-backdrop-filter", "blur(1px)")
  )
    return {
      enhance() {},
    };
  const surfaceSelector =
    ".app-header, aside, dialog, #composer, .composer-options, .conversation-menu, .mode-menu, .settings-select-menu, .liquid-panel";
  let lensId = 0;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const reducedTransparency = matchMedia(
    "(prefers-reduced-transparency: reduce)",
  );
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.classList.add("glass-definitions");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const defs = document.createElementNS(svgNS, "defs");
  svg.append(defs);
  document.body.append(svg);

  // WebKit uses the CSS lens rim. Chromium can also displace live backdrop pixels.
  const canRefract =
    CSS.supports("backdrop-filter", 'url("#glass-lens")') &&
    /(?:Chrome|Chromium|Edg)\//.test(navigator.userAgent);
  const optics = new Map();
  function updateLens(surface, width, height) {
    if (!canRefract || reducedTransparency.matches || width < 1 || height < 1)
      return;
    // Embedded menus inside the drawer use its material, rather than another lens.
    if (surface.closest("#mobile-conversation-controls")) return;
    const state = optics.get(surface);
    if (!state) return;
    const radius = Math.min(
      parseFloat(getComputedStyle(surface).borderTopLeftRadius) || 22,
      width / 2,
      height / 2,
    );
    const signature = `${width}:${height}:${radius}`;
    if (state.signature === signature) return;
    state.signature = signature;
    const scale = Math.min(1, 640 / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.ceil(width * scale));
    canvas.height = Math.max(1, Math.ceil(height * scale));
    const context = canvas.getContext("2d");
    if (!context) return;
    const image = context.createImageData(canvas.width, canvas.height);
    const rim = Math.min(18, radius);

    // A rounded-rectangle normal field bends only the rim, leaving the center flat.
    for (let y = 0; y < canvas.height; y++) {
      for (let x = 0; x < canvas.width; x++) {
        const px = ((x + 0.5) / canvas.width - 0.5) * width;
        const py = ((y + 0.5) / canvas.height - 0.5) * height;
        const qx = Math.abs(px) - width / 2 + radius;
        const qy = Math.abs(py) - height / 2 + radius;
        const corner = Math.hypot(Math.max(qx, 0), Math.max(qy, 0));
        const depth = radius - corner - Math.min(Math.max(qx, qy), 0);
        let nx = 0,
          ny = 0;
        if (depth >= 0 && depth < rim) {
          const bend = Math.pow(1 - depth / rim, 2);
          if (qx > 0 && qy > 0) {
            nx = (qx / corner) * Math.sign(px) * bend;
            ny = (qy / corner) * Math.sign(py) * bend;
          } else if (qx > qy) nx = Math.sign(px) * bend;
          else ny = Math.sign(py) * bend;
        }
        const offset = (y * canvas.width + x) * 4;
        image.data[offset] = Math.round(127.5 + nx * 127.5);
        image.data[offset + 1] = Math.round(127.5 + ny * 127.5);
        image.data[offset + 2] = 128;
        image.data[offset + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);
    state.map.setAttribute("href", canvas.toDataURL());
    state.map.setAttribute("width", width);
    state.map.setAttribute("height", height);
    surface.classList.add("has-refraction");
  }
  const observer = scope.observe(
    new ResizeObserver((entries) => {
      for (const { target } of entries) {
        updateLens(target, target.clientWidth, target.clientHeight);
      }
    }),
  );
  function enhance(root = document) {
    for (const [surface, state] of optics) {
      if (surface.isConnected) continue;
      observer.unobserve(surface);
      state.filter.remove();
      optics.delete(surface);
    }
    const surfaces = [
      ...(root.matches?.(surfaceSelector) ? [root] : []),
      ...root.querySelectorAll(surfaceSelector),
    ];
    for (const surface of surfaces) {
      if (optics.has(surface)) continue;
      if (surface.matches("aside, dialog")) {
        const content = document.createElement("div");
        content.className = "glass-content";
        content.append(...surface.childNodes);
        surface.append(content);
      }
      const layer = document.createElement("span");
      layer.className = "glass-optics";
      layer.setAttribute("aria-hidden", "true");
      surface.prepend(layer);
      surface.classList.add("glass-surface");
      const filter = document.createElementNS(svgNS, "filter");
      filter.id = `glass-lens-${lensId++}`;
      for (const [key, value] of Object.entries({
        x: "0",
        y: "0",
        width: "100%",
        height: "100%",
        "color-interpolation-filters": "sRGB",
      }))
        filter.setAttribute(key, value);
      const map = document.createElementNS(svgNS, "feImage");
      map.setAttribute("result", "lens-map");
      map.setAttribute("preserveAspectRatio", "none");
      const displacement = document.createElementNS(svgNS, "feDisplacementMap");
      for (const [key, value] of Object.entries({
        in: "SourceGraphic",
        in2: "lens-map",
        scale: "-16",
        xChannelSelector: "R",
        yChannelSelector: "G",
      }))
        displacement.setAttribute(key, value);
      filter.append(map, displacement);
      defs.append(filter);
      optics.set(surface, {
        map,
        filter,
        signature: "",
      });
      surface.style.setProperty("--glass-refraction", `url("#${filter.id}")`);
      observer.observe(surface);
      let lightFrame = 0;
      function moveLight(event) {
        if (reducedMotion.matches || reducedTransparency.matches || lightFrame)
          return;
        const { clientX, clientY } = event;
        lightFrame = scope.requestAnimationFrame(() => {
          const rect = surface.getBoundingClientRect();
          surface.style.setProperty("--light-x", `${clientX - rect.left}px`);
          surface.style.setProperty("--light-y", `${clientY - rect.top}px`);
          lightFrame = 0;
        });
      }
      scope.listen(surface, "pointermove", moveLight, {
        passive: true,
      });
      scope.listen(
        surface,
        "pointerdown",
        (event) => {
          if (event.pointerType === "mouse") return;
          moveLight(event);
          surface.classList.add("glass-pressed");
        },
        {
          passive: true,
        },
      );
      for (const event of ["pointerup", "pointercancel", "pointerleave"])
        scope.listen(
          surface,
          event,
          () => surface.classList.remove("glass-pressed"),
          {
            passive: true,
          },
        );
    }
  }
  scope.onDispose(() => {
    for (const [surface] of optics) {
      surface.querySelector(":scope > .glass-optics")?.remove();
      const content = surface.querySelector(":scope > .glass-content");
      if (content) {
        content.replaceWith(...content.childNodes);
      }
      surface.classList.remove(
        "glass-surface",
        "has-refraction",
        "glass-pressed",
      );
      surface.style.removeProperty("--glass-refraction");
    }
    optics.clear();
    svg.remove();
  });
  enhance();
  return {
    enhance,
  };
}
