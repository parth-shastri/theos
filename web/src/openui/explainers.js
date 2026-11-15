import { createElement as h, useId, useRef, useState } from "react";
import { Icon } from "../components/Icon.js";
import { cardIcons, CardHeader } from "./rich-cards.js";
import { exactNumber } from "./chart-data.js";

function ChoiceButtons({
  label,
  choices,
  active,
  onSelect,
  controls,
  buttons,
}) {
  return h(
    "div",
    {
      className: "openui-explainer-choices",
      role: "group",
      "aria-label": label,
    },
    choices.map((choice, i) =>
      h(
        "button",
        {
          key: i,
          type: "button",
          "aria-pressed": i === active,
          "aria-controls": controls,
          onClick: () => onSelect(i),
          ref: buttons
            ? (button) => {
                buttons.current[i] = button;
              }
            : undefined,
        },
        [
          cardIcons.includes(choice.icon)
            ? h(Icon, { name: choice.icon, key: "icon" })
            : null,
          choice.label,
        ],
      ),
    ),
  );
}

function RelationshipList({ links, active, nodes, incoming, onSelect }) {
  const matches = links.filter(
    (link) => (incoming ? link.to : link.from) === active,
  );
  if (!matches.length) return null;
  return h(
    "ul",
    {
      className: "openui-relationship-list",
      "aria-label": incoming ? "Incoming connections" : "Outgoing connections",
    },
    matches.map(({ from, to, label }) => {
      const peer = incoming ? from : to;
      return h(
        "li",
        {
          key: `${from}-${to}-${label}`,
          className: incoming ? "is-incoming" : "is-outgoing",
        },
        [
          h(
            "span",
            {
              className: "openui-relationship-arrow",
              "aria-hidden": true,
              key: "arrow",
            },
            incoming ? "←" : "→",
          ),
          h("div", { key: "connection" }, [
            h(
              "span",
              { className: "openui-card-context", key: "label" },
              label,
            ),
            h(
              "button",
              {
                type: "button",
                key: "peer",
                "aria-label":
                  (incoming ? "From " : "To ") +
                  nodes[peer].label +
                  " · " +
                  label,
                onClick: () => onSelect(peer),
              },
              nodes[peer].label,
            ),
          ]),
        ],
      );
    }),
  );
}

export function RelationshipDiagram({ title, nodes = [], links = [] }) {
  const [selected, setSelected] = useState(0);
  const detailId = useId();
  const buttons = useRef([]);
  const follow = (i) => {
    setSelected(i);
    buttons.current[i]?.focus();
  };
  const items = nodes.map((node) => node?.props ?? node);
  const edges = [];
  const seen = new Set();
  for (const link of links) {
    const { from, to, label } = link?.props ?? link ?? {};
    if (
      !Number.isInteger(from) ||
      !Number.isInteger(to) ||
      from === to ||
      !items[from]?.label ||
      !items[to]?.label ||
      !label
    )
      continue;
    const key = JSON.stringify([from, to, label]);
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ from, to, label });
  }
  const active = items[selected]?.label ? selected : 0;
  const current = items[active];
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-relationship-card" },
    [
      h(CardHeader, { key: "heading", title, icon: "connection" }),
      current && items.every((node) => node?.label) && edges.length
        ? [
            h(ChoiceButtons, {
              key: "choices",
              label: "Choose a concept",
              choices: items,
              active,
              onSelect: setSelected,
              controls: detailId,
              buttons,
            }),
            h(
              "div",
              {
                key: "detail",
                id: detailId,
                className: "openui-explainer-detail",
              },
              [
                h(
                  "p",
                  {
                    key: "summary",
                    className: "openui-card-detail",
                    "aria-live": "polite",
                    "aria-atomic": true,
                  },
                  [
                    h("strong", { key: "label" }, current.label),
                    current.description ? " · " + current.description : null,
                  ],
                ),
                h(RelationshipList, {
                  key: "incoming",
                  links: edges,
                  active,
                  nodes: items,
                  incoming: true,
                  onSelect: follow,
                }),
                h(RelationshipList, {
                  key: "outgoing",
                  links: edges,
                  active,
                  nodes: items,
                  onSelect: follow,
                }),
              ],
            ),
          ]
        : h(
            "p",
            { key: "empty", className: "openui-card-note" },
            "No connections available.",
          ),
    ],
  );
}

export function ScenarioExplorer({
  title,
  result_label: resultLabel,
  scenarios = [],
  unit,
  assumptions,
  icon,
}) {
  const [selected, setSelected] = useState(0);
  const detailId = useId();
  const items = scenarios
    .map((node) => node?.props ?? node)
    .filter((item) => item?.label && Number.isFinite(item.result));
  const active = Math.min(selected, items.length - 1);
  const current = items[active];
  return h(
    "section",
    { className: "openui-visual openui-rich-card openui-scenario-card" },
    [
      h(CardHeader, { key: "heading", title, icon: icon ?? "scale" }),
      assumptions
        ? h(
            "p",
            { className: "openui-card-note", key: "assumptions" },
            assumptions,
          )
        : null,
      current
        ? [
            h(ChoiceButtons, {
              key: "choices",
              label: "Choose a scenario",
              choices: items,
              active,
              onSelect: setSelected,
              controls: detailId,
            }),
            h(
              "div",
              {
                key: "result",
                id: detailId,
                "aria-live": "polite",
                "aria-atomic": true,
                className: "openui-scenario-result",
              },
              [
                h("p", { key: "value", className: "openui-card-stat" }, [
                  h("strong", { key: "number" }, exactNumber(current.result)),
                  unit ? h("span", { key: "unit" }, unit) : null,
                ]),
                h("p", { key: "detail", className: "openui-card-note" }, [
                  h("strong", { key: "label" }, resultLabel),
                  current.detail ? " · " + current.detail : null,
                ]),
              ],
            ),
          ]
        : h(
            "p",
            { key: "empty", className: "openui-card-note" },
            "No scenario results available.",
          ),
    ],
  );
}
