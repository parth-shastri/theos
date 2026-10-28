import { useEffect, useRef } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Glass, Icon } from "./Primitives";
import { ConversationActions } from "./Conversation";
export default function Sidebar() {
  const {
    agentName,
    brand,
    theme,
    toggleTheme,
    mobile,
    sidebarOpen,
    setSidebarOpen,
    me,
    sessions,
    chat,
    usage,
    busy,
    perform,
    openSession,
    newSession,
    navigate,
    openDialog,
    signOut,
  } = useWorkspace();
  const sidebar = useRef(null);
  const close = () => {
    setSidebarOpen(false);
    document.getElementById("toggle-sidebar")?.focus();
  };
  useEffect(() => {
    if (!mobile || !sidebarOpen) return;
    const keyboard = (event) => {
      if (event.key === "Escape") close();
      if (event.key !== "Tab") return;
      const controls = [
        document.getElementById("toggle-sidebar"),
        ...sidebar.current.querySelectorAll(
          "button:not(:disabled):not([hidden])",
        ),
      ].filter((control) => control?.getClientRects().length);
      const first = controls[0],
        last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keyboard);
    return () => document.removeEventListener("keydown", keyboard);
  }, [mobile, sidebarOpen]);
  const label = "Switch to " + (theme === "dark" ? "light" : "dark") + " mode";
  return (
    <>
      <button
        id="sidebar-backdrop"
        className="sidebar-backdrop"
        type="button"
        tabIndex={-1}
        aria-label="Close conversation sidebar"
        hidden={!(mobile && sidebarOpen)}
        onClick={close}
      />
      <Glass
        as="aside"
        id="sidebar"
        aria-label="Workspace navigation"
        inert={!sidebarOpen}
        ref={sidebar}
      >
        <div className="sidebar-brand">
          <img src={brand} data-brand="" className="brand-mark" alt="" />
          <span>{agentName}</span>
          <button
            id="sidebar-theme-toggle"
            className="icon-button"
            type="button"
            aria-label={label}
            title={label}
            onClick={toggleTheme}
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
        </div>
        <button
          id="new-session"
          className="primary new-session"
          disabled={busy}
          onClick={() => perform(newSession)}
        >
          ＋ New conversation
        </button>
        <div id="mobile-conversation-controls" className="mobile-only">
          {mobile && <ConversationActions />}
        </div>
        <div className="rail-title">Conversations</div>
        <nav id="sessions" aria-label="Conversations">
          {sessions.map((session) => (
            <button
              className={session.id === chat.id ? "active" : ""}
              title={session.title}
              disabled={busy}
              aria-current={session.id === chat.id ? "page" : undefined}
              key={session.id}
              onClick={() => perform(() => openSession(session.id))}
            >
              {session.title}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div id="user-cost" className="cost-label">
            {me ? "Your total cost: " + formatCost(usage) : ""}
          </div>
          <button
            id="sidebar-settings-button"
            className="mobile-only"
            type="button"
            aria-haspopup="dialog"
            aria-controls="generation-dialog"
            disabled={busy}
            onClick={() => openDialog("settings")}
          >
            <Icon name="settings" />
            Settings
          </button>
          <button
            id="connections-button"
            disabled={busy}
            onClick={() => navigate("connections-view")}
          >
            Connections <Icon name="arrowUpRight" className="link-arrow" />
          </button>
          <button
            id="tools-button"
            disabled={busy}
            onClick={() => navigate("tools-view")}
          >
            Tools <Icon name="arrowUpRight" className="link-arrow" />
          </button>
          <button
            id="activity-button"
            disabled={busy}
            onClick={() => navigate("dashboard")}
          >
            Activity & usage <Icon name="arrowUpRight" className="link-arrow" />
          </button>
          <button
            id="dashboard-button"
            hidden={!me?.admin}
            disabled={busy}
            onClick={() => navigate("dashboard-admin")}
          >
            Admin dashboard <Icon name="arrowUpRight" className="link-arrow" />
          </button>
          <div className="account-row">
            <span id="identity" title={me?.id}>
              {me?.display_name || me?.id}
            </span>
            <button id="sign-out" onClick={signOut}>
              Sign out
            </button>
          </div>
        </div>
      </Glass>
    </>
  );
}
