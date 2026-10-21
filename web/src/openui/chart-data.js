// Keep missing samples distinct from zero. All plotted series share one unit.
export const chartColors = [
  "var(--accent)",
  "var(--chart-output)",
  "var(--openui-blue)",
  "var(--openui-rose)",
];
export function chartData(labels, series) {
  if (
    !Array.isArray(labels) ||
    !labels.length ||
    labels.some((l) => typeof l !== "string") ||
    !Array.isArray(series) ||
    !series.length
  )
    return null;
  const rows = series.map((node) => node?.props || node);
  if (
    rows.some(
      (row) =>
        !row ||
        typeof row.name !== "string" ||
        !Array.isArray(row.values) ||
        row.values.length !== labels.length ||
        row.values.some(
          (v) => v !== null && (typeof v !== "number" || !Number.isFinite(v)),
        ),
    )
  )
    return null;
  return rows;
}
export function chartScale(rows) {
  const values = rows.flatMap((r) => r.values).filter((v) => v !== null);
  const low = Math.min(0, ...values),
    high = Math.max(0, ...values);
  const span = high - low || 1;
  return { low, high: high === low ? low + 1 : high, span };
}
export function lineRuns(values, x, y) {
  const runs = [];
  let run = [];
  values.forEach((value, i) => {
    if (value === null) {
      if (run.length) runs.push(run);
      run = [];
    } else run.push([x(i), y(value)]);
  });
  if (run.length) runs.push(run);
  return runs;
}
export function compactNumber(value) {
  return new Intl.NumberFormat(undefined, {
    notation: Math.abs(value) >= 10000 ? "compact" : "standard",
    maximumFractionDigits: 2,
  }).format(value);
}
export function exactNumber(value) {
  return value === null
    ? "No data"
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 }).format(
        value,
      );
}
