export default function Connections({ agentName }) {
  return (
    <>
      <section
        id="connections-view"
        className="workspace-panel"
        hidden
        aria-labelledby="connections-title"
      >
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Your workspace</span>
            <h1 id="connections-title">Connections</h1>
          </div>
          <button
            id="back-connections"
            className="panel-back"
            aria-label="Back to chat"
            title="Back to chat"
          >
            <span>Back to chat</span>
          </button>
        </div>
        <p className="panel-description">
          Connect your own accounts. Connections and personal records are
          available across your private conversations.
        </p>
        <div className="connection-heading">
          <div className="section-title">
            <h2>Your accounts</h2>
            <span id="connection-summary"></span>
          </div>
          <button id="refresh-connections" className="soft-button">
            Refresh
          </button>
        </div>
        <p id="connections-status" role="status" aria-live="polite"></p>
        <div id="account-connections"></div>
        <h2 className="connection-heading">Workspace services</h2>
        <p>
          Configured by the operator. These labels show availability, not a live
          service check. Each conversation uses its own sandbox.
        </p>
        <div className="services-panel liquid-panel">
          <div id="workspace-services" className="service-grid"></div>
        </div>
      </section>
    </>
  );
}
