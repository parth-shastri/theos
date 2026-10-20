import { Fragment, memo, useEffect, useId, useRef, useState } from "react";
import { Glass } from "./Primitives";
import {
  number,
  compact,
  money,
  date,
  dailyGeometry,
  nextChartDay,
  rankingData,
} from "../state/chartData";
function ChartValues({ title, headings, rows }) {
  return (
    <details className="chart-data">
      <summary>View exact values</summary>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Chart values. Scroll for more columns."
      >
        <table>
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr>
              {headings.map((heading) => (
                <th scope="col" key={heading}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {row.map((value, index) => (
                  <td key={index}>{String(value)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
function ChartCard({ title, value, caption, kind, children }) {
  return (
    <Glass as="figure" className={"chart-card liquid-panel chart-" + kind}>
      <figcaption className="chart-heading">
        <h3>{title}</h3>
        <strong className="chart-value">{value}</strong>
        <p>{caption}</p>
      </figcaption>
      {children}
    </Glass>
  );
}
function DailyChart({ daily, cost, title }) {
  const [selected, setSelected] = useState(Math.max(0, daily.length - 1)),
    [width, setWidth] = useState(600);
  const plot = useRef(null),
    hits = useRef([]);
  const fillId = "chart-fill-" + useId().replaceAll(":", "");
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0)
        setWidth(Math.max(220, entry.contentRect.width));
    });
    observer.observe(plot.current);
    return () => observer.disconnect();
  }, []);
  const {
    insight,
    height,
    left,
    right,
    top,
    plotHeight,
    maximum,
    step,
    x,
    y,
    labelIndexes,
    runs,
  } = dailyGeometry(daily, cost, width);
  const row = daily[selected];
  return (
    <>
      <p className="chart-insight">{insight}</p>
      <div className="chart-plot" ref={plot}>
        {!!daily.length && (
          <svg
            viewBox={"0 0 " + width + " " + height}
            role="group"
            aria-label={
              (cost ? "Recorded USD cost" : "Model requests") +
              " by UTC day. Use arrow keys on a day to inspect values."
            }
            className="daily-chart"
          >
            <title>
              {cost ? "Daily recorded cost in USD" : "Daily model requests"}
            </title>
            <defs>
              <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
                <stop
                  offset="0%"
                  stopColor="var(--accent)"
                  stopOpacity={cost ? ".25" : ".95"}
                />
                <stop
                  offset="100%"
                  stopColor="var(--accent)"
                  stopOpacity={cost ? ".02" : ".55"}
                />
              </linearGradient>
            </defs>
            {Array.from({ length: 5 }, (_, tick) => {
              const yy = top + plotHeight - (tick * plotHeight) / 4;
              return (
                <Fragment key={tick}>
                  <line
                    x1={left}
                    x2={width - right}
                    y1={yy}
                    y2={yy}
                    className="chart-gridline"
                  />
                  <text
                    x={left - 10}
                    y={yy + 4}
                    textAnchor="end"
                    className="chart-axis"
                  >
                    {cost
                      ? money((maximum * tick) / 4)
                      : compact((maximum * tick) / 4)}
                  </text>
                </Fragment>
              );
            })}
            {labelIndexes.map((index) => (
              <text
                x={x(index)}
                y={height - 8}
                textAnchor={
                  index === 0
                    ? "start"
                    : index === daily.length - 1
                      ? "end"
                      : "middle"
                }
                className="chart-axis"
                key={index}
              >
                {date(daily[index].date)}
              </text>
            ))}
            {runs.map((points, index) => {
              const path = points
                .map(([px, py], index) => (index ? "L" : "M") + px + " " + py)
                .join(" ");
              return (
                <Fragment key={index}>
                  {points.length > 1 && (
                    <path
                      d={
                        path +
                        " L" +
                        points.at(-1)[0] +
                        " " +
                        y(0) +
                        " L" +
                        points[0][0] +
                        " " +
                        y(0) +
                        " Z"
                      }
                      fill={"url(#" + fillId + ")"}
                      className="cost-area"
                    />
                  )}
                  <path d={path} className="cost-line" />
                </Fragment>
              );
            })}
            {daily.map((row, index) =>
              cost ? (
                <circle
                  cx={x(index)}
                  cy={row.cost === null ? y(0) : y(row.cost)}
                  r={row.cost === null ? 4 : row.cost ? 3 : 1.5}
                  className={
                    (row.cost === null ? "cost-unknown" : "cost-point") +
                    (index === selected ? " is-selected" : "")
                  }
                  key={index}
                />
              ) : (
                <rect
                  x={x(index) - Math.min(26, step * 0.65) / 2}
                  y={y(row.requests)}
                  width={Math.min(26, step * 0.65)}
                  height={
                    row.requests ? (row.requests / maximum) * plotHeight : 1
                  }
                  rx={3}
                  fill={"url(#" + fillId + ")"}
                  className={
                    "request-bar" +
                    (row.requests ? "" : " is-zero") +
                    (index === selected ? " is-selected" : "")
                  }
                  key={index}
                />
              ),
            )}
            <line
              x1={x(selected)}
              x2={x(selected)}
              y1={top}
              y2={y(0)}
              className="chart-cursor"
            />
            {daily.map((row, index) => {
              const label =
                date(row.date) +
                " UTC: " +
                (cost
                  ? money(row.cost) +
                    (row.unpriced_requests
                      ? " · " +
                        number(row.unpriced_requests) +
                        " unpriced requests"
                      : "")
                  : number(row.requests) + " model requests");
              return (
                <rect
                  x={left + index * step}
                  y={top}
                  width={step}
                  height={plotHeight + 8}
                  className="chart-hit"
                  role="button"
                  aria-label={label}
                  aria-pressed={index === selected}
                  tabIndex={index === selected ? 0 : -1}
                  key={index}
                  ref={(element) => {
                    hits.current[index] = element;
                  }}
                  onPointerEnter={() => setSelected(index)}
                  onClick={() => setSelected(index)}
                  onFocus={() => setSelected(index)}
                  onKeyDown={(event) => {
                    if (
                      ["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                        event.key,
                      )
                    ) {
                      event.preventDefault();
                      const next = nextChartDay(index, event.key, daily.length);
                      setSelected(next);
                      hits.current[next]?.focus({ preventScroll: true });
                    } else if (["Enter", " "].includes(event.key)) {
                      event.preventDefault();
                      setSelected(index);
                    }
                  }}
                >
                  <title>{label}</title>
                </rect>
              );
            })}
          </svg>
        )}
      </div>
      <div className="chart-inspection" role="status" aria-atomic="true">
        {row && (
          <>
            <span className="inspection-date">{date(row.date) + " · UTC"}</span>
            <strong>
              {cost ? money(row.cost) : number(row.requests) + " requests"}
            </strong>
            <small>
              {cost
                ? row.unpriced_requests
                  ? number(row.unpriced_requests) +
                    " unpriced requests excluded"
                  : "Recorded cost · USD"
                : number(row.input_tokens) +
                  " input · " +
                  number(row.output_tokens) +
                  " output tokens"}
            </small>
          </>
        )}
      </div>
      <p className="chart-hint">Tap a day or use ← → to explore.</p>
      {cost && daily.some((row) => row.unpriced_requests) && (
        <p className="chart-note">
          Unpriced requests are excluded. Hollow points mark days without
          recorded prices.
        </p>
      )}
      {!daily.some((row) => row.requests) && (
        <p className="chart-empty">No model requests in this period.</p>
      )}
      <ChartValues
        title={title}
        headings={
          cost
            ? ["UTC date", "Recorded USD", "Unpriced requests"]
            : ["UTC date", "Requests", "Input tokens", "Output tokens"]
        }
        rows={daily.map((row) =>
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
        )}
      />
    </>
  );
}
function Ranking({ rows, model, title }) {
  const [detail, setDetail] = useState(
    model
      ? "Includes input and output tokens for every model request."
      : "Counts tool starts by the main agent.",
  );
  const { name, visible, value, maximum, total, exactRows } = rankingData(
    rows,
    model,
  );
  return (
    <>
      {model && (
        <div className="chart-legend">
          <span className="legend-input">Input</span>
          <span className="legend-output">Output</span>
        </div>
      )}
      <div className="chart-ranking">
        {visible.map((row, index) => {
          const description = model
            ? row.model +
              ": " +
              number(row.input_tokens) +
              " input tokens, " +
              number(row.output_tokens) +
              " output tokens, " +
              number(row.requests) +
              " requests"
            : row.tool + ": " + number(row.calls) + " tool calls";
          const share = total
            ? Math.round((value(row) / total) * 1000) / 10
            : 0;
          return (
            <button
              className="rank-item"
              type="button"
              title={description}
              aria-label={description}
              key={index}
              onPointerEnter={() => setDetail(description)}
              onFocus={() => setDetail(description)}
              onClick={() => setDetail(description)}
            >
              <span className="rank-label">
                <span className="rank-name">
                  <small>{String(index + 1).padStart(2, "0")}</small>
                  <span>{row[name]}</span>
                </span>
                <strong>{number(value(row))}</strong>
              </span>
              <span className="rank-track">
                <span
                  className="rank-input"
                  style={{
                    width:
                      ((model ? row.input_tokens : row.calls) / maximum) * 100 +
                      "%",
                  }}
                />
                {model && (
                  <span
                    className="rank-output"
                    style={{ width: (row.output_tokens / maximum) * 100 + "%" }}
                  />
                )}
              </span>
              <span className="rank-meta">
                <span>
                  {model
                    ? number(row.input_tokens) +
                      " in · " +
                      number(row.output_tokens) +
                      " out"
                    : number(row.calls) + " calls"}
                </span>
                <span>{share + "% of " + (model ? "tokens" : "calls")}</span>
              </span>
            </button>
          );
        })}
      </div>
      {rows.length ? (
        <p className="chart-detail" role="status">
          {detail}
        </p>
      ) : (
        <p className="chart-empty">
          {model
            ? "No model usage in this period."
            : "No tool calls in this period."}
        </p>
      )}
      <ChartValues
        title={title}
        headings={
          model
            ? ["Model", "Requests", "Input tokens", "Output tokens"]
            : ["Tool", "Calls"]
        }
        rows={exactRows.map((row) =>
          model
            ? [
                row.model,
                number(row.requests),
                number(row.input_tokens),
                number(row.output_tokens),
              ]
            : [row.tool, number(row.calls)],
        )}
      />
    </>
  );
}
function ActivityCharts({ data }) {
  const period = "Last " + data.days + " days · UTC";
  return (
    <section className="activity-charts" aria-label="Activity charts">
      <ChartCard
        title="Model requests"
        value={number(data.totals.requests)}
        caption="Includes conversation, title, and delegate requests."
        kind="requests"
      >
        <DailyChart title="Model requests" daily={data.daily} />
      </ChartCard>
      <ChartCard
        title="Recorded cost"
        value={money(data.totals.cost)}
        caption={
          data.totals.unpriced_requests
            ? number(data.totals.unpriced_requests) +
              " requests have no recorded price."
            : "Provider amounts or configured rates · USD"
        }
        kind="cost"
      >
        <DailyChart title="Recorded cost" daily={data.daily} cost />
      </ChartCard>
      <ChartCard
        title="Tokens by model"
        value={number(data.totals.input_tokens + data.totals.output_tokens)}
        caption={period}
        kind="models"
      >
        <Ranking title="Tokens by model" rows={data.models} model />
      </ChartCard>
      <ChartCard
        title="Tool activity"
        value={number(data.tools.reduce((sum, row) => sum + row.calls, 0))}
        caption={period + " · Main-agent tool starts"}
        kind="tools"
      >
        <Ranking title="Tool activity" rows={data.tools} />
      </ChartCard>
    </section>
  );
}
export default memo(ActivityCharts);
