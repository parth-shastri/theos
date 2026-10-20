export default function WorkspaceHeader({ agentName }) {
  return (
    <>
      <header className="app-header">
        <div className="header-brand">
          <button
            id="toggle-sidebar"
            className="icon-button sidebar-toggle"
            aria-label="Toggle conversation sidebar"
            aria-controls="sidebar"
            aria-expanded="true"
            title="Toggle conversation sidebar"
          ></button>
          <img
            src="/static/brand.png"
            data-brand=""
            className="brand-mark"
            alt=""
          />
          <div>
            <h1>{agentName}</h1>
            <span>Personal assistant workspace</span>
          </div>
        </div>
        <div
          id="mobile-conversation-heading"
          className="mobile-conversation-heading"
        >
          <span id="mobile-session-title">New conversation</span>
          <span id="mobile-conversation-cost" className="cost-label"></span>
        </div>
        <div className="header-actions">
          <button
            id="generation-button"
            aria-label="Settings"
            aria-haspopup="dialog"
            aria-controls="generation-dialog"
          >
            <span className="settings-label">Settings</span>
          </button>
          <button
            id="theme-toggle"
            className="icon-button"
            aria-label="Switch color theme"
            title="Switch color theme"
          >
            ◐
          </button>
        </div>
      </header>
    </>
  );
}
