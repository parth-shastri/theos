import { useEffect, useMemo, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Glass, Icon, SelectPicker } from "./Primitives";
import ActivityCharts from "./ActivityCharts";
import PanelHeading from "./PanelHeading";
const labels = {
  owner: "User",
  id: "Conversation",
  input_tokens: "Input tokens",
  output_tokens: "Output tokens",
  cache_tokens: "Cached tokens",
  cost: "Recorded USD",
  unpriced_requests: "Unpriced",
  error_type: "Error type",
};
const numeric = new Set([
  "requests",
  "input_tokens",
  "output_tokens",
  "cache_tokens",
  "cost",
  "unpriced_requests",
  "attempts",
]);
function DataTable({ title, rows, keys }) {
  return (
    <Glass as="details" className="data-panel liquid-panel">
      <summary className="data-panel-heading">
        <span className="data-panel-title">
          <strong>{title}</strong>
          <small>
            {rows.length.toLocaleString() +
              " " +
              (rows.length === 1 ? "record" : "records") +
              " · all time"}
          </small>
        </span>
        <Icon name="chevron" />
      </summary>
      {!rows.length ? (
        <p className="table-empty">No records yet.</p>
      ) : (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label={title + " table. Scroll horizontally for more columns."}
        >
          <table>
            <caption className="sr-only">
              {title + " · all-time records"}
            </caption>
            <thead>
              <tr>
                {keys.map((key) => (
                  <th
                    className={numeric.has(key) ? "numeric" : ""}
                    scope="col"
                    key={key}
                  >
                    {labels[key] || key.replaceAll("_", " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {keys.map((key) => (
                    <td
                      className={
                        (numeric.has(key) ? "numeric" : "") +
                        (["id", "session"].includes(key) ? " record-id" : "")
                      }
                      key={key}
                    >
                      {key === "cost"
                        ? formatCost(row)
                        : row[key] == null
                          ? "Unavailable"
                          : typeof row[key] === "number"
                            ? row[key].toLocaleString()
                            : String(row[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Glass>
  );
}
export default function Activity() {
  const { view, navigate, brand, json, me } = useWorkspace();
  const active = ["dashboard", "dashboard-admin"].includes(view),
    admin = view === "dashboard-admin";
  const [range, setRange] = useState("30"),
    [refresh, setRefresh] = useState(0),
    [result, setResult] = useState(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const endpoint =
    "/api/" + (admin ? "dashboard" : "activity") + "?days=" + range;
  const options = useMemo(
    () =>
      ["7", "30", "90"].map((value) => ({
        value,
        label: "Last " + value + " days",
      })),
    [],
  );
  useEffect(() => {
    if (!active || !me) return;
    const controller = new AbortController();
    setResult(null);
    setLoading(true);
    setError("");
    Promise.all([
      json(endpoint, {
        signal: controller.signal,
      }),
      admin
        ? json("/api/logs", { signal: controller.signal })
        : Promise.resolve([]),
    ])
      .then(([data, logs]) => {
        if (!controller.signal.aborted)
          setResult({ endpoint, account: me, data, logs });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [active, admin, endpoint, refresh, json, me]);
  const data =
    result?.endpoint === endpoint && result.account === me ? result.data : null;
  return (
    <section id="dashboard" aria-labelledby="dashboard-title" hidden={!active}>
      <PanelHeading active={active} glass className="dashboard-heading">
        <div className="panel-identity">
          <img
            src={brand}
            data-brand=""
            className="panel-brand"
            width="40"
            height="40"
            alt=""
          />
          <div>
            <span id="dashboard-eyebrow" className="eyebrow">
              {admin ? "Workspace insights" : "Personal insights"}
            </span>
            <h1 id="dashboard-title">
              {admin ? "Admin dashboard" : "Activity & usage"}
            </h1>
          </div>
        </div>
        <button
          id="back-chat"
          className="panel-back"
          aria-label="Back to chat"
          title="Back to chat"
          onClick={() => navigate("chat-view")}
        >
          <Icon name="back" />
          <span>Back to chat</span>
        </button>
      </PanelHeading>
      <p id="dashboard-description" className="panel-description">
        {admin
          ? "A clear view of usage across all users and transports."
          : "Your conversations, model usage, and recorded costs in one place."}
      </p>
      <Glass className="dashboard-controls liquid-panel">
        <div className="dashboard-range-field">
          <SelectPicker
            id="dashboard-range"
            label="Chart period"
            value={range}
            options={options}
            onChange={setRange}
            icon="calendar"
            disabled={loading}
            describedBy="dashboard-range-hint"
          />
        </div>
        <span id="dashboard-range-hint">
          Charts use UTC dates. Totals and tables cover all time.
        </span>
        <button
          id="dashboard-refresh"
          className="soft-button"
          disabled={loading}
          aria-busy={loading ? true : undefined}
          onClick={() => setRefresh((value) => value + 1)}
        >
          <Icon name="refresh" />
          Refresh
        </button>
      </Glass>
      <p
        id="dashboard-status"
        role="status"
        hidden={!loading && !error}
        className={"panel-status" + (error ? " error" : "")}
      >
        {error || "Loading activity…"}
      </p>
      <div id="dashboard-content" aria-busy={loading ? true : undefined}>
        {data && (
          <>
            <Glass as="section" className="dashboard-overview liquid-panel">
              <h2>Lifetime overview</h2>
              <p className="dashboard-caption">
                {admin ? "All users · all time" : "Your account · all time"}
              </p>
              <div className="stats">
                {[
                  ...(admin
                    ? [[data.totals.users.toLocaleString(), "Users", "users"]]
                    : []),
                  [
                    data.totals.conversations.toLocaleString(),
                    "Conversations",
                    "chat",
                  ],
                  [
                    (
                      data.totals.input_tokens + data.totals.output_tokens
                    ).toLocaleString(),
                    "Tokens processed",
                    "activity",
                  ],
                  [formatCost(data.totals), "Recorded cost · USD", "wallet"],
                ].map(([value, label, icon]) => (
                  <div className="stat" key={label}>
                    <span className="stat-label">
                      <Icon name={icon} />
                      <span>{label}</span>
                    </span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </div>
              <p className="cost-label">
                {data.totals.unpriced_requests
                  ? data.totals.unpriced_requests.toLocaleString() +
                    " requests have no recorded price. Cost totals include priced requests only."
                  : "Costs use provider-reported amounts or configured token rates."}
              </p>
            </Glass>
            <div className="section-title chart-section-heading">
              <h2>Activity at a glance</h2>
              <span>{"Last " + data.activity.days + " days · UTC"}</span>
            </div>
            <ActivityCharts data={data.activity} />
            <section className="dashboard-records">
              <div className="section-title">
                <h2>Explore the details</h2>
                <span>All-time records</span>
              </div>
              {admin && (
                <DataTable
                  title="Usage per user"
                  rows={data.cost_per_user}
                  keys={[
                    "owner",
                    "requests",
                    "input_tokens",
                    "output_tokens",
                    "cache_tokens",
                    "cost",
                    "unpriced_requests",
                  ]}
                />
              )}
              <DataTable
                title="Cost per conversation"
                rows={data.cost_per_conversation}
                keys={[
                  ...(admin ? ["owner"] : []),
                  "id",
                  "channel",
                  "requests",
                  "cost",
                  "unpriced_requests",
                ]}
              />
              <DataTable
                title="Usage by model"
                rows={data.usage}
                keys={[
                  ...(admin ? ["owner"] : []),
                  "model",
                  "requests",
                  "input_tokens",
                  "output_tokens",
                  "cache_tokens",
                  "cost",
                  "unpriced_requests",
                ]}
              />
              {admin && (
                <>
                  <DataTable
                    title="Conversations"
                    rows={data.sessions}
                    keys={["owner", "id", "channel", "status"]}
                  />
                  <DataTable
                    title="Background work"
                    rows={data.jobs}
                    keys={["kind", "owner", "status", "attempts"]}
                  />
                  <DataTable
                    title="Traces"
                    rows={data.traces}
                    keys={["session", "event", "tool", "status"]}
                  />
                  <DataTable
                    title="Application logs"
                    rows={result.logs}
                    keys={["time", "event", "error_type"]}
                  />
                </>
              )}
            </section>
          </>
        )}
      </div>
    </section>
  );
}
