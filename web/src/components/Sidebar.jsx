import { useCallback, useEffect, useRef } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Glass, Icon } from "./Primitives";

export default function Sidebar() {
  const {
    agentName,
    brand,
    theme,
    toggleTheme,
    mobile,
    sidebarOpen,
    setSidebarOpen,
    workspacePanel,
    setWorkspacePanel,
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
  const account = useRef(null);
  const accountOpen = workspacePanel === "account";
  const historyOpen = sidebarOpen && !(mobile && accountOpen);
  const identity = me.display_name?.trim() || me.id;
  const themeLabel =
    "Switch to " + (theme === "dark" ? "light" : "dark") + " mode";
  const closeSidebar = useCallback(() => {
    setSidebarOpen(false);
    if (mobile) setWorkspacePanel(null);
    requestAnimationFrame(() =>
      document.getElementById("toggle-sidebar")?.focus(),
    );
  }, [mobile, setSidebarOpen, setWorkspacePanel]);
  const closeAccount = useCallback(() => {
    setWorkspacePanel(null);
    requestAnimationFrame(() =>
      document.getElementById("account-button")?.focus(),
    );
  }, [setWorkspacePanel]);

  useEffect(() => {
    if (!historyOpen && !accountOpen) return;
    const panel = accountOpen ? account.current : sidebar.current;
    if (mobile || accountOpen) panel.querySelector("button")?.focus();

    const keydown = (event) => {
      if (event.defaultPrevented || document.querySelector("dialog[open]"))
        return;
      if (
        event.key === "Escape" &&
        (mobile || accountOpen || panel.contains(event.target))
      ) {
        event.preventDefault();
        if (accountOpen) closeAccount();
        else closeSidebar();
      }
      if (event.key !== "Tab" || !mobile) return;
      const controls = [...panel.querySelectorAll("button:not(:disabled)")];
      const boundary = event.shiftKey ? controls[0] : controls.at(-1);
      if (document.activeElement === boundary) {
        event.preventDefault();
        (event.shiftKey ? controls.at(-1) : controls[0])?.focus();
      }
    };
    const outside = (event) => {
      if (
        !panel.contains(event.target) &&
        !document.getElementById("account-button")?.contains(event.target)
      )
        setWorkspacePanel((current) =>
          current === "account" ? null : current,
        );
    };
    document.addEventListener("keydown", keydown);
    if (accountOpen && !mobile)
      document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("pointerdown", outside);
    };
  }, [
    historyOpen,
    accountOpen,
    mobile,
    closeAccount,
    closeSidebar,
    setWorkspacePanel,
  ]);

  const start = () => perform(newSession);

  return (
    <>
      {!mobile && (
        <div className="focus-rail" aria-label="Workspace navigation">
          <img
            src={brand}
            data-brand=""
            className="brand-mark"
            alt={agentName}
          />
          <button
            id="new-session"
            type="button"
            className="primary icon-button focus-button"
            aria-label="New conversation"
            title="New conversation"
            disabled={busy}
            onClick={start}
          >
            <Icon name="compose" />
          </button>
          <button
            id="toggle-sidebar"
            type="button"
            className="icon-button focus-button"
            aria-label="Toggle conversation sidebar"
            title="Conversations"
            aria-expanded={historyOpen}
            aria-controls="sidebar"
            onClick={() => setSidebarOpen((value) => !value)}
          >
            <Icon name="sidebar" />
          </button>
          <button
            id="account-button"
            type="button"
            className="icon-button focus-button"
            aria-label={`Account for ${identity}`}
            title={identity}
            aria-expanded={accountOpen}
            aria-controls="account-menu"
            onClick={() => setWorkspacePanel(accountOpen ? null : "account")}
          >
            <span className="account-initial" aria-hidden="true">
              {Array.from(identity)[0]?.toLocaleUpperCase()}
            </span>
          </button>
        </div>
      )}

      <button
        type="button"
        className="sidebar-backdrop"
        tabIndex={-1}
        aria-label="Close workspace navigation"
        hidden={!(mobile && sidebarOpen)}
        onClick={closeSidebar}
      />
      <Glass
        as="section"
        id="sidebar"
        className="focus-sidebar liquid-panel"
        aria-label="Recent conversations"
        role={mobile ? "dialog" : undefined}
        aria-modal={mobile ? true : undefined}
        hidden={!historyOpen}
        ref={sidebar}
      >
        <div className="focus-drawer-heading">
          <h2>Recent conversations</h2>
          <div className="sidebar-actions">
            <button
              id="theme-toggle"
              type="button"
              className="icon-button focus-button"
              aria-label={themeLabel}
              title={themeLabel}
              onClick={toggleTheme}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} />
            </button>
            {mobile && (
              <button
                type="button"
                className="icon-button focus-button"
                aria-label="Close recent conversations"
                onClick={closeSidebar}
              >
                <Icon name="close" />
              </button>
            )}
          </div>
        </div>
        {mobile && (
          <button
            id="new-session"
            type="button"
            className="primary"
            disabled={busy}
            onClick={start}
          >
            <Icon name="compose" /> New conversation
          </button>
        )}
        <nav id="sessions" aria-label="Conversations">
          {sessions.map((session) => (
            <button
              className={session.id === chat.id ? "active" : ""}
              title={session.title}
              disabled={busy}
              aria-current={session.id === chat.id ? "page" : undefined}
              key={session.id}
              onClick={() => {
                if (mobile) closeSidebar();
                perform(() => openSession(session.id));
              }}
            >
              {session.title}
            </button>
          ))}
        </nav>
        {mobile && (
          <button
            id="account-button"
            type="button"
            className="account-drawer-entry"
            aria-controls="account-menu"
            onClick={() => setWorkspacePanel("account")}
          >
            <span className="account-initial" aria-hidden="true">
              {Array.from(identity)[0]?.toLocaleUpperCase()}
            </span>
            <span>{identity}</span>
          </button>
        )}
      </Glass>

      <Glass
        as="section"
        id="account-menu"
        className="focus-account-menu liquid-panel"
        aria-label="Workspace account"
        role={mobile ? "dialog" : undefined}
        aria-modal={mobile ? true : undefined}
        hidden={!accountOpen}
        ref={account}
      >
        <div className="focus-drawer-heading">
          <h2 id="identity" title={me.id}>
            {identity}
          </h2>
          <button
            type="button"
            className="icon-button focus-button"
            aria-label="Close account"
            onClick={closeAccount}
          >
            <Icon name="close" />
          </button>
        </div>
        <p id="user-cost" className="cost-label">
          {"Your total cost: " + formatCost(usage)}
        </p>
        <div className="account-actions">
          <button
            id="generation-button"
            type="button"
            aria-haspopup="dialog"
            aria-controls="generation-dialog"
            disabled={busy}
            onClick={() => openDialog("settings")}
          >
            Settings
          </button>
          <button
            id="connections-button"
            type="button"
            disabled={busy}
            onClick={() => navigate("connections-view")}
          >
            Connections
          </button>
          <button
            id="account-notifications-button"
            type="button"
            onClick={() => navigate("notifications-view")}
          >
            Notifications
          </button>
          <button
            id="tools-button"
            type="button"
            disabled={busy}
            onClick={() => navigate("tools-view")}
          >
            Tools
          </button>
          <button
            id="activity-button"
            type="button"
            disabled={busy}
            onClick={() => navigate("dashboard")}
          >
            Activity &amp; usage
          </button>
          {me.admin && (
            <button
              id="dashboard-button"
              type="button"
              disabled={busy}
              onClick={() => navigate("dashboard-admin")}
            >
              Admin dashboard
            </button>
          )}
          <button
            id="account-password-button"
            type="button"
            aria-haspopup="dialog"
            aria-controls="account-password-dialog"
            onClick={() => openDialog("password")}
            disabled={busy}
          >
            Browser password
          </button>
          <button id="sign-out" type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </Glass>
    </>
  );
}
