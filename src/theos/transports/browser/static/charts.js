"use strict";
window.TheosCharts = (() => {
  const observers = new Set();
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
          maximumFractionDigits: 6,
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
  function card(title, value, caption) {
    const figure = node("figure", "", "chart-card");
    const heading = node("figcaption", "", "chart-heading");
    heading.append(
      node("h2", title),
      node("strong", value, "chart-value"),
      node("p", caption),
    );
    figure.append(heading);
    return figure;
  }
  function dataTable(figure, headings, rows) {
    const details = node("details", "", "chart-data");
    details.append(node("summary", "View chart data"));
    const scroll = node("div", "", "table-scroll");
    const table = node("table");
    const header = node("tr");
    for (const heading of headings) {
      const cell = node("th", heading);
      cell.scope = "col";
      header.append(cell);
    }
    const thead = node("thead");
    thead.append(header);
    table.append(thead);
    const tbody = node("tbody");
    for (const values of rows) {
      const row = node("tr");
      for (const value of values) row.append(node("td", String(value)));
      tbody.append(row);
    }
    table.append(tbody);
    scroll.append(table);
    details.append(scroll);
    figure.append(details);
  }
  function dailyChart(figure, daily, metric) {
    const cost = metric === "cost";
    const plot = node("div", "", "chart-plot");
    const detail = node("p", "Hover or tap to inspect a day.", "chart-detail");
    function draw(width) {
      const height = 224,
        left = cost ? 78 : 44,
        right = 16,
        top = 16,
        bottom = 40;
      const plotWidth = width - left - right,
        plotHeight = height - top - bottom;
      const values = daily.map((row) => row[metric]);
      const peak = Math.max(0, ...values.filter((value) => value !== null));
      const magnitude = 10 ** Math.floor(Math.log10(peak || 1));
      const costMaximum =
        [1, 2, 4, 5, 8, 10]
          .map((value) => value * magnitude)
          .find((value) => value >= peak) || magnitude * 10;
      const maximum = cost ? costMaximum : Math.max(4, Math.ceil(peak / 4) * 4);
      const svg = svgNode("svg", {
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": `${cost ? "Recorded cost" : "Model requests"} by day. Exact values are available in the chart data table.`,
        class: "daily-chart",
      });
      svg.append(
        svgNode(
          "title",
          {},
          cost ? "Daily recorded cost in USD" : "Daily model requests",
        ),
      );
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
      const labelIndexes =
        width < 420
          ? [0, Math.round((daily.length - 1) / 2), daily.length - 1]
          : [
              ...new Set([
                0,
                Math.round((daily.length - 1) / 4),
                Math.round((daily.length - 1) / 2),
                Math.round(((daily.length - 1) * 3) / 4),
                daily.length - 1,
              ]),
            ];
      for (const index of labelIndexes)
        svg.append(
          svgNode(
            "text",
            {
              x: x(index),
              y: height - 14,
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
      if (cost) {
        let path = "",
          connected = false;
        daily.forEach((row, index) => {
          if (row.cost === null) {
            connected = false;
            return;
          }
          path += `${connected ? "L" : "M"}${x(index)} ${y(row.cost)} `;
          connected = true;
        });
        svg.append(svgNode("path", { d: path, class: "cost-line" }));
      }
      daily.forEach((row, index) => {
        if (cost) {
          svg.append(
            svgNode("circle", {
              cx: x(index),
              cy: row.cost === null ? y(0) : y(row.cost),
              r: row.cost === null ? 4 : 2.5,
              class: row.cost === null ? "cost-unknown" : "cost-point",
            }),
          );
        } else {
          const barWidth = Math.min(24, step * 0.65);
          svg.append(
            svgNode("rect", {
              x: x(index) - barWidth / 2,
              y: y(row.requests),
              width: barWidth,
              height: Math.max(1, (row.requests / maximum) * plotHeight),
              rx: 2,
              class: row.requests ? "request-bar" : "request-bar is-zero",
            }),
          );
        }
        const label = `${date(row.date)}: ${cost ? money(row.cost) + (row.unpriced_requests ? ` · ${number(row.unpriced_requests)} unpriced requests` : "") : number(row.requests) + " model requests"}`;
        const hit = svgNode("rect", {
          x: left + index * step,
          y: top,
          width: step,
          height: plotHeight + 8,
          class: "chart-hit",
        });
        hit.append(svgNode("title", {}, label));
        const inspect = () => {
          detail.textContent = label;
        };
        hit.onpointerenter = hit.onclick = inspect;
        svg.append(hit);
      });
      plot.replaceChildren(svg);
    }
    draw(600);
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0)
        draw(Math.max(240, entry.contentRect.width));
    });
    observer.observe(plot);
    observers.add(observer);
    figure.append(plot, detail);
    if (cost && daily.some((row) => row.unpriced_requests))
      figure.append(
        node(
          "p",
          "Unpriced requests are excluded. Hollow points mark days with no recorded price.",
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
        : ["UTC date", "Model requests", "Input tokens", "Output tokens"],
      daily.map((row) =>
        cost
          ? [
              row.date,
              row.cost === null ? "Unavailable" : row.cost.toFixed(6),
              row.unpriced_requests,
            ]
          : [row.date, row.requests, row.input_tokens, row.output_tokens],
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
    const list = node("div", "", "chart-ranking");
    if (model) {
      const legend = node("div", "", "chart-legend");
      legend.append(
        node("span", "Input", "legend-input"),
        node("span", "Output", "legend-output"),
      );
      figure.append(legend);
    }
    for (const row of visible) {
      const item = node("button", "", "rank-item");
      item.type = "button";
      const label = node("span", "", "rank-label");
      label.append(node("span", row[name]), node("strong", number(value(row))));
      const track = node("span", "", "rank-track");
      const input = node("span", "", "rank-input");
      input.style.width = `${((model ? row.input_tokens : row.calls) / maximum) * 100}%`;
      track.append(input);
      if (model) {
        const output = node("span", "", "rank-output");
        output.style.width = `${(row.output_tokens / maximum) * 100}%`;
        track.append(output);
      }
      const description = model
        ? `${row.model}: ${number(row.input_tokens)} input tokens, ${number(row.output_tokens)} output tokens, ${number(row.requests)} requests`
        : `${row.tool}: ${number(row.calls)} tool calls`;
      item.title = description;
      item.setAttribute("aria-label", description);
      item.append(label, track);
      list.append(item);
    }
    const detail = node(
      "p",
      model
        ? "Select a model to inspect its token breakdown."
        : "Select a tool to inspect its calls.",
      "chart-detail",
    );
    for (const item of list.children)
      item.onpointerenter =
        item.onfocus =
        item.onclick =
          () => {
            detail.textContent = item.getAttribute("aria-label");
          };
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
          ? [row.model, row.requests, row.input_tokens, row.output_tokens]
          : [row.tool, row.calls],
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
      `${period}. Includes title and delegate requests.`,
    );
    dailyChart(requests, data.daily, "requests");
    const cost = card(
      "Recorded cost",
      money(data.totals.cost),
      `${period}${data.totals.unpriced_requests ? ` · ${number(data.totals.unpriced_requests)} unpriced requests` : " · USD"}`,
    );
    dailyChart(cost, data.daily, "cost");
    const models = card(
      "Tokens by model",
      number(data.totals.input_tokens + data.totals.output_tokens),
      period,
    );
    ranking(models, data.models, true);
    const tools = card(
      "Tool activity",
      number(data.tools.reduce((sum, row) => sum + row.calls, 0)),
      `${period} · Main-agent tool starts`,
    );
    ranking(tools, data.tools);
    grid.append(requests, cost, models, tools);
    return grid;
  }
  return { activity };
})();
