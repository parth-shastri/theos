import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Glass, Icon } from "./Primitives";
export default function WorkspaceHeader() {
  const {
    agentName,
    brand,
    chat,
    view,
    theme,
    toggleTheme,
    sidebarOpen,
    setSidebarOpen,
    mobile,
    busy,
    openDialog,
    setPanelHeadingHost,
  } = useWorkspace();
  const toggle = () => {
    setSidebarOpen(!sidebarOpen);
    if (!sidebarOpen && mobile)
      requestAnimationFrame(() =>
        document.getElementById("new-session")?.focus(),
      );
  };
  const label = "Switch to " + (theme === "dark" ? "light" : "dark") + " mode";
  return (
    <>
      <Glass
        as="header"
        className={
          "app-header" + (view !== "chat-view" ? " app-header-compact" : "")
        }
      >
        <div className="header-brand">
          <button
            id="toggle-sidebar"
            className="icon-button sidebar-toggle"
            aria-label="Toggle conversation sidebar"
            aria-controls="sidebar"
            aria-expanded={sidebarOpen}
            title="Toggle conversation sidebar"
            onClick={toggle}
          >
            <Icon name="sidebar" />
          </button>
          <img src={brand} data-brand="" className="brand-mark" alt="" />
          <div>
            <h1>{agentName}</h1>
            <span>Personal assistant workspace</span>
          </div>
        </div>
        <div
          id="mobile-conversation-heading"
          className="mobile-conversation-heading"
          hidden={view !== "chat-view"}
        >
          <span id="mobile-session-title" title={chat.title}>
            {chat.title}
          </span>
          <span id="mobile-conversation-cost" className="cost-label">
            {chat.id ? "Conversation cost: " + formatCost(chat.usage) : ""}
          </span>
        </div>
        <div className="header-actions" inert={mobile && sidebarOpen}>
          <button
            id="generation-button"
            aria-label="Settings"
            aria-haspopup="dialog"
            aria-controls="generation-dialog"
            disabled={busy}
            onClick={() => openDialog("settings")}
          >
            <Icon name="settings" />
            <span className="settings-label">Settings</span>
          </button>
          <button
            id="theme-toggle"
            className="icon-button"
            aria-label={label}
            title={label}
            onClick={toggleTheme}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
        </div>
      </Glass>
      <div
        className="mobile-panel-header"
        ref={setPanelHeadingHost}
        hidden={view === "chat-view" || sidebarOpen}
        inert={sidebarOpen}
      />
    </>
  );
}
