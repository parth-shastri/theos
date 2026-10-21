import { createElement as h, useEffect, useId, useRef, useState } from "react";
import {
  chartColors,
  chartData,
  chartScale,
  compactNumber,
  exactNumber,
  lineRuns,
} from "./chart-data.js";

function Heading({ title, subtitle, trailing }) {
  return h("div", { className: "openui-visual-heading" }, [
    h("div", { key: "copy" }, [
      h("h3", { key: "title" }, title),
      subtitle ? h("p", { key: "sub" }, subtitle) : null,
    ]),
    trailing
      ? h("span", { className: "openui-unit", key: "unit" }, trailing)
      : null,
  ]);
}
function ExactValues({ title, columns, rows }) {
  return h("details", { className: "openui-exact-values" }, [
    h("summary", { key: "toggle" }, "View exact values"),
    h(Table, { key: "table", title, columns, rows, embedded: true }),
  ]);
}
export function Table({ title, columns = [], rows = [], caption, embedded }) {
  return h(
    embedded ? "div" : "section",
    { className: embedded ? "" : "openui-visual openui-data-table" },
    [
      !embedded
        ? h(Heading, { key: "heading", title, subtitle: caption })
        : null,
      h(
        "div",
        {
          className: "openui-table-scroll",
          tabIndex: 0,
          role: "region",
          "aria-label": title + ". Scroll for more columns.",
          key: "scroll",
        },
        h("table", {}, [
          h("caption", { className: "sr-only", key: "caption" }, title),
          h(
            "thead",
            { key: "head" },
            h(
              "tr",
              {},
              columns.map((label, i) =>
                h("th", { scope: "col", key: i }, label),
              ),
            ),
          ),
          h(
            "tbody",
            { key: "body" },
            rows.map((row, i) =>
              h(
                "tr",
                { key: i },
                columns.map((_, col) =>
                  h(
                    "td",
                    { key: col },
                    row[col] === null || row[col] === undefined
                      ? "No data"
                      : String(row[col]),
                  ),
                ),
              ),
            ),
          ),
        ]),
      ),
    ],
  );
}
export function MetricTile({ label, value, unit, detail, trend }) {
  return h("div", { className: "openui-metric" }, [
    h("span", { className: "openui-metric-label", key: "label" }, label),
    h("div", { className: "openui-metric-value", key: "value" }, [
      h("strong", { key: "number" }, value),
      unit ? h("span", { key: "unit" }, unit) : null,
    ]),
    detail
      ? h("span", { className: "openui-metric-detail", key: "detail" }, detail)
      : null,
    trend
      ? h("span", { className: "openui-metric-trend", key: "trend" }, trend)
      : null,
  ]);
}
export function Progress({ label, value, target, unit = "", detail }) {
  if (!(target > 0) || !Number.isFinite(target) || !Number.isFinite(value))
    return h("p", {}, "A verified value and goal are needed to show progress.");
  const percent = Math.max(0, Math.min(100, (value / target) * 100));
  return h("section", { className: "openui-visual openui-progress" }, [
    h(
      "div",
      {
        className: "openui-progress-ring",
        key: "ring",
        role: "img",
        "aria-label": `${label}: ${exactNumber(value)} of ${exactNumber(target)} ${unit}, ${Math.round((value / target) * 100)} percent`,
      },
      [
        h("svg", { viewBox: "0 0 112 112", "aria-hidden": true, key: "svg" }, [
          h("circle", {
            cx: 56,
            cy: 56,
            r: 46,
            fill: "none",
            className: "openui-ring-track",
            strokeWidth: 8,
            key: "track",
          }),
          h("circle", {
            cx: 56,
            cy: 56,
            r: 46,
            fill: "none",
            stroke: "var(--accent)",
            strokeWidth: 8,
            strokeLinecap: "round",
            pathLength: 100,
            strokeDasharray: `${percent} 100`,
            transform: "rotate(-90 56 56)",
            key: "value",
          }),
        ]),
        h(
          "strong",
          { key: "percent" },
          Math.round((value / target) * 100) + "%",
        ),
      ],
    ),
    h("div", { className: "openui-progress-copy", key: "copy" }, [
      h("h3", { key: "title" }, label),
      h("p", { className: "openui-progress-value", key: "value" }, [
        h("strong", { key: "current" }, exactNumber(value)),
        h("span", { key: "target" }, ` / ${exactNumber(target)} ${unit}`),
      ]),
      detail ? h("p", { key: "detail" }, detail) : null,
    ]),
  ]);
}
export function DataChart({
  title,
  labels = [],
  series = [],
  unit = "",
  caption,
  kind = "bar",
}) {
  const [selected, setSelected] = useState(null),
    [hidden, setHidden] = useState([]),
    [width, setWidth] = useState(560);
  const plot = useRef(null),
    points = useRef([]);
  const uid = useId().replaceAll(":", "");
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0)
        setWidth(Math.max(220, entry.contentRect.width));
    });
    if (plot.current) observer.observe(plot.current);
    return () => observer.disconnect();
  }, []);
  const rows = chartData(labels, series);
  if (!rows)
    return h("section", { className: "openui-visual" }, [
      h(Heading, { key: "heading", title }),
      h(
        "p",
        { key: "empty", className: "openui-chart-empty" },
        "The chart needs matching labels and values. Missing values must be marked as no data.",
      ),
    ]);
  const visible = rows
    .map((r, i) => ({ ...r, index: i }))
    .filter((r) => !hidden.includes(r.index));
  const { low, high, span } = chartScale(visible);
  const left = 48,
    right = 12,
    top = 18,
    bottom = 34,
    height = 236,
    inner = width - left - right,
    plotHeight = height - top - bottom;
  const step = inner / Math.max(1, labels.length),
    x = (i) => left + step * (i + 0.5),
    y = (v) => top + ((high - v) / span) * plotHeight;
  const tickEvery = Math.max(
    1,
    Math.ceil(labels.length / (width < 380 ? 4 : 7)),
  );
  const active =
    selected !== null && selected < labels.length ? selected : null;
  const select = (i) => setSelected(i);
  const keydown = (event, i) => {
    const next =
      event.key === "ArrowRight"
        ? Math.min(labels.length - 1, i + 1)
        : event.key === "ArrowLeft"
          ? Math.max(0, i - 1)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? labels.length - 1
              : null;
    if (next !== null) {
      event.preventDefault();
      setSelected(next);
      points.current[next]?.focus({ preventScroll: true });
    }
  };
  const svg = [];
  svg.push(h("title", { key: "title" }, title));
  svg.push(
    h(
      "defs",
      { key: "defs" },
      chartColors.map((color, i) =>
        h(
          "linearGradient",
          { id: uid + "-fill-" + i, x1: 0, x2: 0, y1: 0, y2: 1, key: i },
          [
            h("stop", {
              offset: "0%",
              stopColor: color,
              stopOpacity: 0.23,
              key: 0,
            }),
            h("stop", {
              offset: "100%",
              stopColor: color,
              stopOpacity: 0.01,
              key: 1,
            }),
          ],
        ),
      ),
    ),
  );
  for (let tick = 0; tick < 5; tick++) {
    const value = low + (span * tick) / 4,
      yy = y(value);
    svg.push(
      h("g", { key: "tick-" + tick }, [
        h("line", {
          x1: left,
          x2: width - right,
          y1: yy,
          y2: yy,
          className: "openui-gridline",
          key: 0,
        }),
        h(
          "text",
          {
            x: left - 10,
            y: yy + 4,
            textAnchor: "end",
            className: "openui-axis",
            key: 1,
          },
          compactNumber(value),
        ),
      ]),
    );
  }
  if (active !== null)
    svg.push(
      h("rect", {
        x: left + step * active,
        y: top,
        width: step,
        height: plotHeight,
        fill: "var(--accent)",
        opacity: 0.06,
        rx: 7,
        key: "highlight",
      }),
    );
  for (const row of visible) {
    const color = chartColors[row.index % chartColors.length];
    if (kind === "line") {
      lineRuns(row.values, x, y).forEach((run, i) => {
        const d = run
          .map(([xx, yy], j) => (j ? "L" : "M") + xx + " " + yy)
          .join(" ");
        if (run.length > 1)
          svg.push(
            h("path", {
              d: d + ` L${run.at(-1)[0]} ${y(0)} L${run[0][0]} ${y(0)} Z`,
              fill: `url(#${uid}-fill-${row.index % chartColors.length})`,
              key: `area-${row.index}-${i}`,
            }),
          );
        svg.push(
          h("path", {
            d,
            fill: "none",
            stroke: color,
            strokeWidth: 2.5,
            strokeLinejoin: "round",
            strokeLinecap: "round",
            key: `line-${row.index}-${i}`,
          }),
        );
      });
      row.values.forEach((value, i) => {
        if (value !== null)
          svg.push(
            h("circle", {
              cx: x(i),
              cy: y(value),
              r: active === i ? 5 : 3,
              fill: color,
              stroke: "var(--surface)",
              strokeWidth: 2,
              key: `dot-${row.index}-${i}`,
            }),
          );
      });
    } else {
      const barWidth = Math.min(
        48,
        (step * 0.72) / Math.max(1, visible.length),
      );
      const offset = visible.findIndex((r) => r.index === row.index);
      row.values.forEach((value, i) => {
        if (value !== null)
          svg.push(
            h("rect", {
              x: x(i) - (barWidth * visible.length) / 2 + offset * barWidth + 1,
              y: Math.min(y(value), y(0)),
              width: Math.max(1, barWidth - 2),
              height: Math.max(value === 0 ? 1 : 2, Math.abs(y(0) - y(value))),
              fill: color,
              opacity: active === null || active === i ? 0.9 : 0.4,
              rx: Math.min(5, barWidth / 4),
              key: `bar-${row.index}-${i}`,
            }),
          );
      });
    }
  }
  labels.forEach((label, i) => {
    if (i % tickEvery === 0 || i === labels.length - 1)
      svg.push(
        h(
          "text",
          {
            x: x(i),
            y: height - 8,
            textAnchor: "middle",
            className: "openui-axis",
            key: "label-" + i,
          },
          label.length > 12 ? label.slice(0, 10) + "…" : label,
        ),
      );
    svg.push(
      h("rect", {
        x: left + step * i,
        y: top,
        width: step,
        height: plotHeight,
        fill: "transparent",
        tabIndex: active === i || (active === null && i === 0) ? 0 : -1,
        role: "button",
        "aria-label":
          label +
          ": " +
          visible
            .map((r) => r.name + " " + exactNumber(r.values[i]) + " " + unit)
            .join(", "),
        "aria-pressed": active === i,
        className: "openui-chart-hit",
        ref: (el) => (points.current[i] = el),
        onFocus: () => select(i),
        onKeyDown: (e) => keydown(e, i),
        onClick: () => select(i),
        onPointerMove: () => select(i),
        key: "hit-" + i,
      }),
    );
  });
  return h("figure", { className: "openui-visual openui-chart" }, [
    h(Heading, { title, subtitle: caption, trailing: unit, key: "heading" }),
    h(
      "div",
      { className: "openui-chart-legend", key: "legend" },
      rows.map((row, i) =>
        h(
          "button",
          {
            type: "button",
            "aria-pressed": !hidden.includes(i),
            onClick: () =>
              setHidden((current) =>
                current.includes(i)
                  ? current.filter((n) => n !== i)
                  : current.length === rows.length - 1
                    ? current
                    : [...current, i],
              ),
            key: i,
          },
          [
            h("span", {
              style: { background: chartColors[i % chartColors.length] },
              key: "swatch",
            }),
            row.name,
          ],
        ),
      ),
    ),
    h(
      "div",
      {
        className: "openui-chart-inspection",
        "aria-live": "polite",
        key: "inspection",
      },
      active === null
        ? "Hover, tap, or use arrow keys to inspect"
        : labels[active] +
            " · " +
            visible
              .map(
                (r) =>
                  r.name +
                  ": " +
                  exactNumber(r.values[active]) +
                  (r.values[active] === null ? "" : " " + unit),
              )
              .join(" · "),
    ),
    h(
      "div",
      { className: "openui-chart-plot", ref: plot, key: "plot" },
      h(
        "svg",
        {
          viewBox: `0 0 ${width} ${height}`,
          role: "group",
          "aria-label": title + ". Use arrow keys to inspect values.",
        },
        svg,
      ),
    ),
    h(ExactValues, {
      key: "values",
      title,
      columns: [
        "Label",
        ...rows.map((r) => r.name + (unit ? " (" + unit + ")" : "")),
      ],
      rows: labels.map((label, i) => [label, ...rows.map((r) => r.values[i])]),
    }),
  ]);
}
export function Donut({ title, labels = [], values = [], unit = "", caption }) {
  const [selected, setSelected] = useState(null);
  if (
    !Array.isArray(labels) ||
    !Array.isArray(values) ||
    labels.some((l) => typeof l !== "string") ||
    !labels.length ||
    labels.length !== values.length ||
    values.some((v) => !Number.isFinite(v) || v < 0)
  )
    return h(
      "p",
      {},
      "A composition chart needs matching labels and non-negative values.",
    );
  const total = values.reduce((a, b) => a + b, 0);
  let offset = 0;
  const segments = values.map((value, i) => {
    const share = total ? (value / total) * 100 : 0,
      start = offset;
    offset += share;
    return h("circle", {
      cx: 70,
      cy: 70,
      r: 54,
      pathLength: 100,
      fill: "none",
      stroke: chartColors[i % chartColors.length],
      strokeWidth: 14,
      strokeDasharray: `${Math.max(0, share - 0.8)} ${100 - Math.max(0, share - 0.8)}`,
      strokeDashoffset: -start,
      transform: "rotate(-90 70 70)",
      opacity: selected === null || selected === i ? 1 : 0.25,
      key: i,
    });
  });
  return h("figure", { className: "openui-visual openui-donut" }, [
    h(Heading, { key: "heading", title, subtitle: caption, trailing: unit }),
    h("div", { className: "openui-donut-layout", key: "body" }, [
      h(
        "div",
        {
          className: "openui-donut-ring",
          key: "ring",
          role: "img",
          "aria-label": title + ": " + exactNumber(total) + " " + unit,
        },
        [
          h(
            "svg",
            { viewBox: "0 0 140 140", "aria-hidden": true, key: "svg" },
            [
              h("circle", {
                cx: 70,
                cy: 70,
                r: 54,
                fill: "none",
                strokeWidth: 14,
                className: "openui-ring-track",
                key: "track",
              }),
              ...segments,
            ],
          ),
          h("div", { className: "openui-donut-total", key: "total" }, [
            h(
              "strong",
              { key: "value" },
              exactNumber(selected === null ? total : values[selected]),
            ),
            h(
              "span",
              { key: "label" },
              selected === null ? "Total " + unit : labels[selected],
            ),
          ]),
        ],
      ),
      h(
        "div",
        { className: "openui-donut-legend", key: "legend" },
        labels.map((label, i) =>
          h(
            "button",
            {
              type: "button",
              "aria-pressed": selected === i,
              onClick: () => setSelected(i),
              onFocus: () => setSelected(i),
              onPointerMove: () => setSelected(i),
              key: i,
            },
            [
              h("i", {
                style: { background: chartColors[i % chartColors.length] },
                key: "color",
              }),
              h("span", { key: "label" }, label),
              h("strong", { key: "value" }, exactNumber(values[i])),
              h(
                "small",
                { key: "share" },
                total ? Math.round((values[i] / total) * 100) + "%" : "0%",
              ),
            ],
          ),
        ),
      ),
    ]),
    h(ExactValues, {
      key: "values",
      title,
      columns: ["Label", unit || "Value"],
      rows: labels.map((l, i) => [l, values[i]]),
    }),
  ]);
}
