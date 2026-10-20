export const number = (value) => Number(value || 0).toLocaleString();
export const compact = (value) =>
  new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
export const money = (value) =>
  value === null
    ? "Unavailable"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: value > 0 && value < 0.000001 ? 8 : 6,
      }).format(value);
export const date = (value) =>
  new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(value + "T00:00:00Z"));
export function dailyGeometry(daily, cost, width) {
  const metric = cost ? "cost" : "requests";
  const peak = Math.max(
    0,
    ...daily.map((row) => row[metric]).filter((value) => value !== null),
  );
  const peakDay = daily.find((row) => row[metric] === peak);
  const insight =
    peak && peakDay
      ? "Peak day · " +
        date(peakDay.date) +
        " · " +
        (cost ? money(peak) : number(peak) + " requests")
      : cost && daily.some((row) => row.requests)
        ? daily.some((row) => row.requests && row.cost !== null)
          ? "Priced requests recorded at $0.00."
          : "No prices recorded for these requests."
        : "No model requests in this period.";
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
  const roughStep = Math.max(1, peak / 4),
    tickMagnitude = 10 ** Math.floor(Math.log10(roughStep));
  const requestStep = [1, 2, 5, 10]
    .map((value) => value * tickMagnitude)
    .find((value) => value >= roughStep);
  const maximum = cost ? costMaximum : requestStep * 4,
    step = plotWidth / daily.length;
  const x = (index) => left + (index + 0.5) * step,
    y = (value) => top + plotHeight - (value / maximum) * plotHeight;
  const labelCount = width < 380 ? 2 : width < 540 ? 3 : 5;
  const labelIndexes = [
    ...new Set(
      Array.from({ length: labelCount }, (_, index) =>
        Math.round((index * (daily.length - 1)) / (labelCount - 1)),
      ),
    ),
  ];
  const runs = [];
  let run = [];
  if (cost) {
    daily.forEach((row, index) => {
      if (row.cost !== null) run.push([x(index), y(row.cost)]);
      else if (run.length) {
        runs.push(run);
        run = [];
      }
    });
    if (run.length) runs.push(run);
  }

  return {
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
  };
}

export function nextChartDay(index, key, length) {
  return key === "Home"
    ? 0
    : key === "End"
      ? length - 1
      : Math.max(
          0,
          Math.min(length - 1, index + (key === "ArrowRight" ? 1 : -1)),
        );
}
export function rankingData(rows, model) {
  const name = model ? "model" : "tool";
  const fields = model
    ? ["input_tokens", "output_tokens", "requests"]
    : ["calls"];
  let visible = rows;
  if (rows.length > 6) {
    const other = {
      [name]:
        "Other " +
        (model ? "models" : "tools") +
        " (" +
        (rows.length - 6) +
        ")",
    };
    for (const field of fields)
      other[field] = rows.slice(6).reduce((sum, row) => sum + row[field], 0);
    visible = [...rows.slice(0, 6), other];
  }
  const value = (row) =>
    model ? row.input_tokens + row.output_tokens : row.calls;
  return {
    name,
    visible,
    value,
    maximum: Math.max(1, ...visible.map(value)),
    total: rows.reduce((sum, row) => sum + value(row), 0),
    exactRows: rows,
  };
}
