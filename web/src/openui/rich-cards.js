import { createElement as h, useId, useState } from "react";
import { Icon } from "../components/Icon.js";
import {
  chartData,
  chartScale,
  compactNumber,
  exactNumber,
} from "./chart-data.js";
import { DonutRing, ExactValues } from "./visuals.js";

export const cardIcons = [
  "activity",
  "timer",
  "calendar",
  "branch",
  "wallet",
  "weather",
  "skills",
  "globe",
  "lock",
  "window",
  "scale",
  "connection",
  "storage",
  "sandbox",
  "check",
  "alert",
  "chat",
  "users",
  "search",
];

export function CardHeader({ title, icon, context }) {
  return h("header", { className: "openui-card-heading" }, [
    h(
      "span",
      { className: "openui-card-icon", key: "icon" },
      h(Icon, { name: cardIcons.includes(icon) ? icon : "activity" }),
    ),
    h("h3", { key: "title" }, title),
    context
      ? h("span", { className: "openui-card-context", key: "context" }, context)
      : null,
  ]);
}

export function TrendCard({
  title,
  labels = [],
  values = [],
  unit,
  icon,
  context,
}) {
  const [selection, setSelection] = useState(null);
  const rows = chartData(labels, [{ name: title, values }]);
  const latest = labels.length - 1;
  const selected =
    selection !== null && selection <= latest ? selection : latest;
  const value = values[selected];
  const previous = values[selected - 1];
  const change =
    Number.isFinite(value) && Number.isFinite(previous)
      ? value - previous
      : null;
  const scale = rows && chartScale(rows);
  const show =
    rows && Number.isFinite(scale.span) && values.some((v) => v !== null);
  const print = (v) =>
    v === null ? "No data" : [exactNumber(v), unit].filter(Boolean).join(" ");
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-trend-card" },
    [
      h(CardHeader, { key: "heading", title, icon, context }),
      show
        ? [
            h(
              "div",
              {
                className: "openui-card-reading",
                key: "reading",
                "aria-live": "polite",
                "aria-atomic": true,
              },
              [
                h("div", { className: "openui-card-stat", key: "value" }, [
                  h("strong", { key: "number" }, exactNumber(value)),
                  value !== null && unit
                    ? h("span", { key: "unit" }, unit)
                    : null,
                ]),
                h("p", { className: "openui-card-note", key: "label" }, [
                  h("strong", { key: "period" }, labels[selected]),
                  Number.isFinite(change) && change !== 0
                    ? ` · ${change > 0 ? "+" : "−"}${exactNumber(Math.abs(change))} vs. ${labels[selected - 1]}`
                    : null,
                ]),
              ],
            ),
            h(
              "div",
              {
                className: "openui-mini-series",
                role: "group",
                "aria-label": title + " observations",
                style: {
                  "--sample-count": labels.length,
                  "--zero-line": (scale.high / scale.span) * 100 + "%",
                },
                key: "chart",
              },
              labels.map((label, i) => {
                const point = values[i];
                const length =
                  point === null ? 0 : (Math.abs(point) / scale.span) * 100;
                const top =
                  point === null
                    ? (scale.high / scale.span) * 100
                    : ((scale.high - Math.max(0, point)) / scale.span) * 100;
                return h(
                  "button",
                  {
                    type: "button",
                    key: i,
                    "aria-label": label + ", " + print(point),
                    "aria-pressed": i === selected,
                    onClick: () => setSelection(i),
                  },
                  [
                    h(
                      "span",
                      {
                        className: "openui-mini-plot",
                        key: "plot",
                        "aria-hidden": true,
                      },
                      [
                        h("span", {
                          className:
                            point === null
                              ? "openui-mini-missing"
                              : "openui-mini-bar",
                          style: {
                            "--bar-top": top + "%",
                            "--bar-size": length + "%",
                          },
                          key: "mark",
                        }),
                      ],
                    ),
                    h(
                      "span",
                      {
                        className: "openui-mini-label",
                        key: "label",
                        "aria-hidden": true,
                      },
                      label,
                    ),
                  ],
                );
              }),
            ),
            h(ExactValues, {
              key: "values",
              title,
              columns: ["Period", unit || "Value"],
              rows: labels.map((label, i) => [label, values[i]]),
            }),
          ]
        : h(
            "p",
            { className: "openui-card-note", key: "empty" },
            "No chart data available.",
          ),
    ],
  );
}

export function ComparisonCard({
  title,
  labels = [],
  values = [],
  unit,
  icon,
  context,
}) {
  const data = chartData(labels, [{ name: title, values }]);
  const high = data ? Math.max(0, ...values.filter(Number.isFinite)) : 0;
  const show =
    data &&
    values.some((v) => v !== null) &&
    values.every((v) => v === null || v >= 0);
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-comparison-card" },
    [
      h(CardHeader, { key: "heading", title, icon, context }),
      show
        ? [
            h(
              "ul",
              { className: "openui-comparison-rows", key: "rows" },
              labels.map((label, i) =>
                h("li", { key: i }, [
                  h(
                    "div",
                    { className: "openui-comparison-label", key: "label" },
                    [
                      h("span", { key: "name" }, label),
                      h(
                        "strong",
                        { key: "value" },
                        values[i] === null
                          ? "No data"
                          : [exactNumber(values[i]), unit]
                              .filter(Boolean)
                              .join(" "),
                      ),
                    ],
                  ),
                  h(
                    "div",
                    {
                      className: "openui-comparison-track",
                      key: "bar",
                      "aria-hidden": true,
                    },
                    values[i] === null
                      ? null
                      : h("span", {
                          style: {
                            width: high ? (values[i] / high) * 100 + "%" : "0%",
                          },
                        }),
                  ),
                ]),
              ),
            ),
            h(
              "div",
              {
                className: "openui-comparison-axis",
                key: "axis",
                "aria-hidden": true,
              },
              [
                h("span", { key: "zero" }, "0"),
                h(
                  "span",
                  { key: "max" },
                  [compactNumber(high), unit].filter(Boolean).join(" "),
                ),
              ],
            ),
          ]
        : h(
            "p",
            { className: "openui-card-note", key: "empty" },
            "No comparable data available.",
          ),
    ],
  );
}

const statusColors = {
  neutral: "var(--openui-card-blue)",
  positive: "var(--success)",
  warning: "var(--warning)",
  blocked: "var(--danger)",
};

export function StatusBreakdown({ title, groups = [], unit, icon, context }) {
  const [selection, setSelection] = useState(0);
  const items = groups.map((node) => node?.props ?? node);
  const values = items.map((item) => item?.count);
  const total = values.reduce((sum, count) => sum + count, 0);
  const show =
    items.length > 0 &&
    Number.isSafeInteger(total) &&
    values.every((v) => Number.isSafeInteger(v) && v >= 0);
  const active = Math.min(selection, items.length - 1);
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-status-breakdown" },
    [
      h(CardHeader, { key: "heading", title, icon, context }),
      show
        ? [
            h(
              "div",
              {
                className: "openui-donut-layout openui-status-layout",
                key: "body",
              },
              [
                h(DonutRing, {
                  key: "ring",
                  total,
                  values,
                  selected: active,
                  colors: items.map(
                    (item) => statusColors[item.tone] ?? statusColors.neutral,
                  ),
                  centerValue: total,
                  centerLabel: unit || "Total",
                  description: [title, exactNumber(total), unit]
                    .filter(Boolean)
                    .join(" "),
                }),
                h(
                  "div",
                  {
                    className: "openui-status-options",
                    role: "group",
                    "aria-label": title + " categories",
                    key: "options",
                  },
                  items.map((item, i) =>
                    h(
                      "button",
                      {
                        type: "button",
                        "aria-pressed": i === active,
                        style: {
                          "--category-color":
                            statusColors[item.tone] ?? statusColors.neutral,
                        },
                        key: i,
                        onClick: () => setSelection(i),
                      },
                      [
                        h(Icon, {
                          name: cardIcons.includes(item.icon)
                            ? item.icon
                            : "activity",
                          key: "icon",
                        }),
                        h("span", { key: "label" }, item.label),
                        h("strong", { key: "count" }, exactNumber(item.count)),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            h(
              "p",
              {
                className: "openui-card-detail",
                "aria-live": "polite",
                "aria-atomic": true,
                key: "detail",
              },
              [
                h("strong", { key: "label" }, items[active].label),
                items[active].detail ? " · " + items[active].detail : null,
              ],
            ),
          ]
        : h(
            "p",
            { className: "openui-card-note", key: "empty" },
            "No status counts available.",
          ),
    ],
  );
}

export function ProcessDiagram({ title, steps = [] }) {
  const [selection, setSelection] = useState(0);
  const detailId = useId();
  const items = steps
    .map((node) => node?.props ?? node)
    .filter((step) => step?.label && step?.description);
  const active = Math.min(selection, items.length - 1);
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-process-card" },
    [
      h(CardHeader, { key: "heading", title, icon: "skills" }),
      items.length
        ? [
            h(
              "ol",
              {
                className: "openui-process-flow",
                key: "flow",
                "aria-label": title + " steps",
              },
              items.map((step, i) =>
                h(
                  "li",
                  { key: i },
                  h(
                    "button",
                    {
                      type: "button",
                      "aria-pressed": i === active,
                      "aria-controls": detailId,
                      onClick: () => setSelection(i),
                    },
                    [
                      h(Icon, {
                        name: cardIcons.includes(step.icon)
                          ? step.icon
                          : "connection",
                        key: "icon",
                      }),
                      h("strong", { key: "label" }, step.label),
                      step.caption
                        ? h("span", { key: "caption" }, step.caption)
                        : null,
                    ],
                  ),
                ),
              ),
            ),
            h(
              "p",
              {
                className: "openui-card-detail",
                id: detailId,
                "aria-live": "polite",
                "aria-atomic": true,
                key: "detail",
              },
              [
                h("strong", { key: "label" }, items[active].label),
                " · " + items[active].description,
              ],
            ),
          ]
        : h(
            "p",
            { className: "openui-card-note", key: "empty" },
            "No steps available.",
          ),
    ],
  );
}

export function LeverExplainer({
  title,
  load_newtons: load,
  length_cm: length,
}) {
  const [pivot, setPivot] = useState(40);
  const id = useId();
  // Integer steps place the pivot exactly one-third along the beam by default.
  const fraction = pivot / 120;
  const left = length * fraction;
  const right = length - left;
  const push = (load * left) / right;
  const scale = 33 / Math.max(load, push);
  const format = (value, unit) => {
    const rounded = Math.round(value * 10) / 10;
    return (
      (Math.abs(value - rounded) > 1e-8 ? "≈" : "") +
      exactNumber(rounded) +
      " " +
      unit
    );
  };
  const loadLabel = format(load, "N");
  const pushLabel = format(push, "N");
  const leftLabel = format(left, "cm");
  const rightLabel = format(right, "cm");
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-lever-card" },
    [
      h(CardHeader, { key: "heading", title, icon: "scale" }),
      Number.isFinite(push) && push > 0
        ? [
            h("div", { className: "openui-lever-layout", key: "body" }, [
              h(
                "div",
                { className: "openui-lever-controls", key: "controls" },
                [
                  h(
                    "p",
                    {
                      className: "openui-card-stat",
                      "aria-live": "polite",
                      "aria-atomic": true,
                      key: "force",
                    },
                    [
                      h("strong", { key: "value" }, pushLabel),
                      h("span", { key: "label" }, "push needed to balance"),
                    ],
                  ),
                  h("label", { htmlFor: id, key: "label" }, "Move the pivot"),
                  h("input", {
                    type: "range",
                    id,
                    min: 30,
                    max: 90,
                    value: pivot,
                    "aria-valuetext": leftLabel + " from the load",
                    onChange: (event) =>
                      setPivot(event.currentTarget.valueAsNumber),
                    key: "slider",
                  }),
                  h(
                    "div",
                    {
                      className: "openui-lever-ends",
                      "aria-hidden": true,
                      key: "ends",
                    },
                    [
                      h("span", { key: "load" }, "Toward load"),
                      h("span", { key: "push" }, "Toward push"),
                    ],
                  ),
                ],
              ),
              h(
                "div",
                {
                  className: "openui-lever-board",
                  role: "img",
                  "aria-label": `${loadLabel} load ${leftLabel} left of the pivot. ${pushLabel} push ${rightLabel} right of the pivot.`,
                  style: {
                    "--pivot": fraction * 100 + "%",
                    "--load-arrow": load * scale + "px",
                    "--push-arrow": push * scale + "px",
                  },
                  key: "diagram",
                },
                h(
                  "div",
                  { className: "openui-lever-beam", "aria-hidden": true },
                  [
                    h(
                      "span",
                      { className: "openui-lever-force is-load", key: "load" },
                      loadLabel + " load",
                    ),
                    h(
                      "span",
                      { className: "openui-lever-force is-push", key: "push" },
                      pushLabel + " push",
                    ),
                    h(
                      "span",
                      { className: "openui-lever-pivot", key: "pivot" },
                      "Pivot",
                    ),
                    h("div", { className: "openui-lever-arms", key: "arms" }, [
                      h("span", { key: "left" }, leftLabel),
                      h("span", { key: "right" }, rightLabel),
                    ]),
                  ],
                ),
              ),
            ]),
            h(
              "p",
              { className: "openui-card-note", key: "note" },
              "On an ideal lever, a longer push arm takes less force to balance the same load.",
            ),
          ]
        : h(
            "p",
            { className: "openui-card-note", key: "empty" },
            "A positive load and beam length are needed.",
          ),
    ],
  );
}
