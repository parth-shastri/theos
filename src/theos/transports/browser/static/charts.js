"use strict";
window.TheosCharts = (() => {
  const observers = new Set();
  let chartId = 0;
  const number = (value) => Number(value || 0).toLocaleString();
  const compact = (value) =>
    new Intl.NumberFormat(undefined, {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  const money = (value) =>
    value === null
      ? "Unavailable"
      : new Intl.NumberFormat("en-US", {
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 2,
          maximumFractionDigits: value > 0 && value < 0.000001 ? 8 : 6,
        }).format(value);
  const date = (value) =>
    new Intl.DateTimeFormat(undefined, {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    }).format(new Date(`${value}T00:00:00Z`));
  function node(tag, text = "", className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    element.className = className;
    return element;
  }
  function svgNode(tag, attributes = {}, text = "") {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [name, value] of Object.entries(attributes))
      element.setAttribute(name, value);
    element.textContent = text;
    return element;
  }
  function card(title, value, caption, kind) {
    const figure = node("figure", "", `chart-card liquid-panel chart-${kind}`);
    const heading = node("figcaption", "", "chart-heading");
    heading.append(
      node("h3", title),
      node("strong", value, "chart-value"),
      node("p", caption),
    );
    figure.append(heading);
    return figure;
  }
  function dataTable(figure, headings, rows) {
    const details = node("details", "", "chart-data");
    details.append(node("summary", "View exact values"));
    const scroll = node("div", "", "table-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "Chart values. Scroll for more columns.");
    const table = node("table");
    table.append(
      node("caption", figure.querySelector("h3").textContent, "sr-only"),
    );
    const header = node("tr");
    for (const heading of headings) {
      const cell = node("th", heading);
      cell.scope = "col";
      header.append(cell);
    }
    const thead = node("thead");
    thead.append(header);
    const tbody = node("tbody");
    for (const values of rows) {
      const row = node("tr");
      for (const value of values) row.append(node("td", String(value)));
      tbody.append(row);
    }
    table.append(thead, tbody);
    scroll.append(table);
    details.append(scroll);
    figure.append(details);
  }
  function dailyChart(figure, daily, metric) {
    const cost = metric === "cost";
    const plot = node("div", "", "chart-plot");
    const detail = node("div", "", "chart-inspection");
    detail.setAttribute("role", "status");
    detail.setAttribute("aria-atomic", "true");
    const hint = node("p", "Tap a day or use ← → to explore.", "chart-hint");
    const values = daily.map((row) => row[metric]);
    const peak = Math.max(0, ...values.filter((value) => value !== null));
    const peakDay = daily.find((row) => row[metric] === peak);
    const insight = node(
      "p",
      peak && peakDay
        ? `Peak day · ${date(peakDay.date)} · ${cost ? money(peak) : number(peak) + " requests"}`
        : cost && daily.some((row) => row.requests)
          ? daily.some((row) => row.requests && row.cost !== null)
            ? "Priced requests recorded at $0.00."
            : "No prices recorded for these requests."
          : "No model requests in this period.",
      "chart-insight",
    );
    figure.append(insight);
    let selected = Math.max(0, daily.length - 1);
    const fillId = `chart-fill-${++chartId}`;
    function draw(width) {
      if (!daily.length) return;
      const height = 232,
        left = cost ? 78 : 40,
        right = 12,
        top = 14,
        bottom = 36;
      const plotWidth = width - left - right,
        plotHeight = height - top - bottom;
      const magnitude = 10 ** Math.floor(Math.log10(peak || 1));
      const costMaximum =
        [1, 2, 4, 5, 8, 10]
          .map((value) => value * magnitude)
          .find((value) => value >= peak) || magnitude * 10;
      const roughStep = Math.max(1, peak / 4);
      const tickMagnitude = 10 ** Math.floor(Math.log10(roughStep));
      const requestStep = [1, 2, 5, 10]
        .map((value) => value * tickMagnitude)
        .find((value) => value >= roughStep);
      const maximum = cost ? costMaximum : requestStep * 4;
      const svg = svgNode("svg", {
        viewBox: `0 0 ${width} ${height}`,
        role: "group",
        "aria-label": `${cost ? "Recorded USD cost" : "Model requests"} by UTC day. Use arrow keys on a day to inspect values.`,
        class: "daily-chart",
      });
      svg.append(
        svgNode(
          "title",
          {},
          cost ? "Daily recorded cost in USD" : "Daily model requests",
        ),
      );
      const defs = svgNode("defs");
      const gradient = svgNode("linearGradient", {
        id: fillId,
        x1: "0",
        x2: "0",
        y1: "0",
        y2: "1",
      });
      gradient.append(
        svgNode("stop", {
          offset: "0%",
          "stop-color": "var(--accent)",
          "stop-opacity": cost ? ".25" : ".95",
        }),
        svgNode("stop", {
          offset: "100%",
          "stop-color": "var(--accent)",
          "stop-opacity": cost ? ".02" : ".55",
        }),
      );
      defs.append(gradient);
      svg.append(defs);
      for (let tick = 0; tick <= 4; tick++) {
        const y = top + plotHeight - (tick * plotHeight) / 4;
        svg.append(
          svgNode("line", {
            x1: left,
            x2: width - right,
            y1: y,
            y2: y,
            class: "chart-gridline",
          }),
        );
        svg.append(
          svgNode(
            "text",
            {
              x: left - 10,
              y: y + 4,
              "text-anchor": "end",
              class: "chart-axis",
            },
            cost ? money((maximum * tick) / 4) : compact((maximum * tick) / 4),
          ),
        );
      }
      const step = plotWidth / daily.length;
      const x = (index) => left + (index + 0.5) * step;
      const y = (value) => top + plotHeight - (value / maximum) * plotHeight;
      const labelCount = width < 380 ? 2 : width < 540 ? 3 : 5;
      const labelIndexes = [
        ...new Set(
          Array.from({ length: labelCount }, (_, index) =>
            Math.round((index * (daily.length - 1)) / (labelCount - 1)),
          ),
        ),
      ];
      for (const index of labelIndexes)
        svg.append(
          svgNode(
            "text",
            {
              x: x(index),
              y: height - 8,
              "text-anchor":
                index === 0
                  ? "start"
                  : index === daily.length - 1
                    ? "end"
                    : "middle",
              class: "chart-axis",
            },
            date(daily[index].date),
          ),
        );
      const marks = [];
      if (cost) {
        // Each known-price run gets its own path. Missing prices never become zero.
        const runs = [];
        let run = [];
        daily.forEach((row, index) => {
          if (row.cost !== null) run.push([x(index), y(row.cost)]);
          else if (run.length) {
            runs.push(run);
            run = [];
          }
        });
        if (run.length) runs.push(run);
        for (const points of runs) {
          const path = points
            .map(([px, py], index) => `${index ? "L" : "M"}${px} ${py}`)
            .join(" ");
          if (points.length > 1)
            svg.append(
              svgNode("path", {
                d: `${path} L${points.at(-1)[0]} ${y(0)} L${points[0][0]} ${y(0)} Z`,
                fill: `url(#${fillId})`,
                class: "cost-area",
              }),
            );
          svg.append(svgNode("path", { d: path, class: "cost-line" }));
        }
      }
      daily.forEach((row, index) => {
        const mark = cost
          ? svgNode("circle", {
              cx: x(index),
              cy: row.cost === null ? y(0) : y(row.cost),
              r: row.cost === null ? 4 : row.cost ? 3 : 1.5,
              class: row.cost === null ? "cost-unknown" : "cost-point",
            })
          : svgNode("rect", {
              x: x(index) - Math.min(26, step * 0.65) / 2,
              y: y(row.requests),
              width: Math.min(26, step * 0.65),
              height: row.requests ? (row.requests / maximum) * plotHeight : 1,
              rx: 3,
              fill: `url(#${fillId})`,
              class: row.requests ? "request-bar" : "request-bar is-zero",
            });
        marks.push(mark);
        svg.append(mark);
      });
      const cursor = svgNode("line", {
        x1: x(selected),
        x2: x(selected),
        y1: top,
        y2: y(0),
        class: "chart-cursor",
      });
      svg.append(cursor);
      const hits = daily.map((row, index) => {
        const label = `${date(row.date)} UTC: ${cost ? money(row.cost) + (row.unpriced_requests ? ` · ${number(row.unpriced_requests)} unpriced requests` : "") : number(row.requests) + " model requests"}`;
        const hit = svgNode("rect", {
          x: left + index * step,
          y: top,
          width: step,
          height: plotHeight + 8,
          class: "chart-hit",
          role: "button",
          "aria-label": label,
          tabindex: index === selected ? "0" : "-1",
        });
        hit.append(svgNode("title", {}, label));
        hit.onpointerenter = hit.onclick = hit.onfocus = () => inspect(index);
        hit.onkeydown = (event) => {
          if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? daily.length - 1
                  : Math.max(
                      0,
                      Math.min(
                        daily.length - 1,
                        index + (event.key === "ArrowRight" ? 1 : -1),
                      ),
                    );
            inspect(next);
            hits[next].focus({ preventScroll: true });
          } else if (["Enter", " "].includes(event.key)) {
            event.preventDefault();
            inspect(index);
          }
        };
        svg.append(hit);
        return hit;
      });
      function inspect(index) {
        selected = index;
        const row = daily[index];
        cursor.setAttribute("x1", x(index));
        cursor.setAttribute("x2", x(index));
        hits.forEach((hit, i) => {
          hit.setAttribute("tabindex", i === index ? "0" : "-1");
          hit.setAttribute("aria-pressed", String(i === index));
          marks[i].classList.toggle("is-selected", i === index);
        });
        const label = node(
          "span",
          date(row.date) + " · UTC",
          "inspection-date",
        );
        const value = node(
          "strong",
          cost ? money(row.cost) : number(row.requests) + " requests",
        );
        const meta = node(
          "small",
          cost
            ? row.unpriced_requests
              ? `${number(row.unpriced_requests)} unpriced requests excluded`
              : "Recorded cost · USD"
            : `${number(row.input_tokens)} input · ${number(row.output_tokens)} output tokens`,
        );
        detail.replaceChildren(label, value, meta);
      }
      inspect(selected);
      plot.replaceChildren(svg);
    }
    draw(600);
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0)
        draw(Math.max(220, entry.contentRect.width));
    });
    observer.observe(plot);
    observers.add(observer);
    figure.append(plot, detail, hint);
    if (cost && daily.some((row) => row.unpriced_requests))
      figure.append(
        node(
          "p",
          "Unpriced requests are excluded. Hollow points mark days without recorded prices.",
          "chart-note",
        ),
      );
    if (!daily.some((row) => row.requests))
      figure.append(
        node("p", "No model requests in this period.", "chart-empty"),
      );
    dataTable(
      figure,
      cost
        ? ["UTC date", "Recorded USD", "Unpriced requests"]
        : ["UTC date", "Requests", "Input tokens", "Output tokens"],
      daily.map((row) =>
        cost
          ? [
              row.date,
              row.cost === null ? "Unavailable" : String(row.cost),
              row.unpriced_requests,
            ]
          : [
              row.date,
              number(row.requests),
              number(row.input_tokens),
              number(row.output_tokens),
            ],
      ),
    );
  }
  function buckets(rows, name, fields, limit = 6) {
    if (rows.length <= limit) return rows;
    const other = {
      [name]: `Other ${name === "model" ? "models" : "tools"} (${rows.length - limit})`,
    };
    for (const field of fields)
      other[field] = rows
        .slice(limit)
        .reduce((sum, row) => sum + row[field], 0);
    return [...rows.slice(0, limit), other];
  }
  function ranking(figure, rows, model = false) {
    const name = model ? "model" : "tool";
    const visible = buckets(
      rows,
      name,
      model ? ["input_tokens", "output_tokens", "requests"] : ["calls"],
    );
    const value = (row) =>
      model ? row.input_tokens + row.output_tokens : row.calls;
    const maximum = Math.max(1, ...visible.map(value));
    const total = rows.reduce((sum, row) => sum + value(row), 0);
    const list = node("div", "", "chart-ranking");
    if (model) {
      const legend = node("div", "", "chart-legend");
      legend.append(
        node("span", "Input", "legend-input"),
        node("span", "Output", "legend-output"),
      );
      figure.append(legend);
    }
    const detail = node(
      "p",
      model
        ? "Includes input and output tokens for every model request."
        : "Counts tool starts by the main agent.",
      "chart-detail",
    );
    detail.setAttribute("role", "status");
    visible.forEach((row, index) => {
      const item = node("button", "", "rank-item");
      item.type = "button";
      const label = node("span", "", "rank-label");
      const identity = node("span", "", "rank-name");
      identity.append(
        node("small", String(index + 1).padStart(2, "0")),
        node("span", row[name]),
      );
      label.append(identity, node("strong", number(value(row))));
      const track = node("span", "", "rank-track");
      const input = node("span", "", "rank-input");
      input.style.width = `${((model ? row.input_tokens : row.calls) / maximum) * 100}%`;
      track.append(input);
      if (model) {
        const output = node("span", "", "rank-output");
        output.style.width = `${(row.output_tokens / maximum) * 100}%`;
        track.append(output);
      }
      const meta = node("span", "", "rank-meta");
      const share = total ? Math.round((value(row) / total) * 1000) / 10 : 0;
      meta.append(
        node(
          "span",
          model
            ? `${number(row.input_tokens)} in · ${number(row.output_tokens)} out`
            : `${number(row.calls)} calls`,
        ),
        node("span", `${share}% of ${model ? "tokens" : "calls"}`),
      );
      const description = model
        ? `${row.model}: ${number(row.input_tokens)} input tokens, ${number(row.output_tokens)} output tokens, ${number(row.requests)} requests`
        : `${row.tool}: ${number(row.calls)} tool calls`;
      item.title = description;
      item.setAttribute("aria-label", description);
      item.append(label, track, meta);
      item.onpointerenter =
        item.onfocus =
        item.onclick =
          () => {
            detail.textContent = description;
          };
      list.append(item);
    });
    figure.append(
      list,
      rows.length
        ? detail
        : node(
            "p",
            model
              ? "No model usage in this period."
              : "No tool calls in this period.",
            "chart-empty",
          ),
    );
    dataTable(
      figure,
      model
        ? ["Model", "Requests", "Input tokens", "Output tokens"]
        : ["Tool", "Calls"],
      rows.map((row) =>
        model
          ? [
              row.model,
              number(row.requests),
              number(row.input_tokens),
              number(row.output_tokens),
            ]
          : [row.tool, number(row.calls)],
      ),
    );
  }
  function activity(data) {
    for (const observer of observers) observer.disconnect();
    observers.clear();
    const grid = node("section", "", "activity-charts");
    grid.setAttribute("aria-label", "Activity charts");
    const period = `Last ${data.days} days · UTC`;
    const requests = card(
      "Model requests",
      number(data.totals.requests),
      "Includes conversation, title, and delegate requests.",
      "requests",
    );
    dailyChart(requests, data.daily, "requests");
    const cost = card(
      "Recorded cost",
      money(data.totals.cost),
      data.totals.unpriced_requests
        ? `${number(data.totals.unpriced_requests)} requests have no recorded price.`
        : "Provider amounts or configured rates · USD",
      "cost",
    );
    dailyChart(cost, data.daily, "cost");
    const models = card(
      "Tokens by model",
      number(data.totals.input_tokens + data.totals.output_tokens),
      period,
      "models",
    );
    ranking(models, data.models, true);
    const tools = card(
      "Tool activity",
      number(data.tools.reduce((sum, row) => sum + row.calls, 0)),
      `${period} · Main-agent tool starts`,
      "tools",
    );
    ranking(tools, data.tools);
    grid.append(requests, cost, models, tools);
    return grid;
  }
  return { activity };
})();
