export default function Activity({ agentName }) {
  return (
    <>
      <section id="dashboard" aria-labelledby="dashboard-title" hidden>
        <div className="panel-heading dashboard-heading liquid-panel">
          <div className="panel-identity">
            <img
              src="/static/brand.png"
              data-brand
              className="panel-brand"
              width="40"
              height="40"
              alt=""
            />
            <div>
              <span id="dashboard-eyebrow" className="eyebrow">
                Personal insights
              </span>
              <h1 id="dashboard-title">Your activity & usage</h1>
            </div>
          </div>
          <button
            id="back-chat"
            className="panel-back"
            aria-label="Back to chat"
            title="Back to chat"
          >
            <span>Back to chat</span>
          </button>
        </div>
        <p id="dashboard-description" className="panel-description"></p>
        <div className="dashboard-controls liquid-panel">
          <div className="dashboard-range-field">
            <label htmlFor="dashboard-range">Chart period</label>
            <select
              id="dashboard-range"
              defaultValue="30"
              aria-describedby="dashboard-range-hint"
            >
              <option value="7">Last 7 days</option>
              <option value="30">Last 30 days</option>
              <option value="90">Last 90 days</option>
            </select>
          </div>
          <span id="dashboard-range-hint">
            Charts use UTC dates. Totals and tables cover all time.
          </span>
          <button id="dashboard-refresh" className="soft-button">
            Refresh
          </button>
        </div>
        <p id="dashboard-status" role="status" hidden></p>
        <div id="dashboard-content"></div>
      </section>
    </>
  );
}
