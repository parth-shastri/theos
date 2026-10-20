export default function Sidebar({ agentName }) {
  return (
    <>
      <button
        id="sidebar-backdrop"
        className="sidebar-backdrop"
        type="button"
        tabIndex="-1"
        aria-label="Close conversation sidebar"
        hidden
      ></button>
      <aside id="sidebar" aria-label="Workspace navigation">
        <div className="sidebar-brand">
          <img
            src="/static/brand.png"
            data-brand=""
            className="brand-mark"
            alt=""
          />
          <span>{agentName}</span>
          <button
            id="sidebar-theme-toggle"
            className="icon-button"
            type="button"
            aria-label="Switch color theme"
          ></button>
        </div>
        <button id="new-session" className="primary new-session">
          ＋ New conversation
        </button>
        <div id="mobile-conversation-controls" className="mobile-only"></div>
        <div className="rail-title">Conversations</div>
        <nav id="sessions" aria-label="Conversations"></nav>
        <div className="sidebar-bottom">
          <div id="user-cost" className="cost-label"></div>
          <button
            id="sidebar-settings-button"
            className="mobile-only"
            type="button"
            aria-haspopup="dialog"
            aria-controls="generation-dialog"
          >
            Settings
          </button>
          <button id="connections-button">Connections ↗</button>
          <button id="tools-button">Tools ↗</button>
          <button id="activity-button">Activity & usage ↗</button>
          <button id="dashboard-button" hidden>
            Admin dashboard ↗
          </button>
          <div className="account-row">
            <span id="identity"></span>
            <button id="sign-out">Sign out</button>
          </div>
        </div>
      </aside>
    </>
  );
}
