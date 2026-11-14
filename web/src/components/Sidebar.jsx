import { useEffect, useRef } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Icon } from "./Primitives";

export default function Sidebar() {
  const {
    agentName,
    brand,
    theme,
    toggleTheme,
    mobile,
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
  const overlay = useRef(null);
  const historyOpen = workspacePanel === "history";
  const accountOpen = workspacePanel === "account";
  const open = historyOpen || accountOpen;
  const identity = me.display_name?.trim() || me.id;
  const themeLabel =
    "Switch to " + (theme === "dark" ? "light" : "dark") + " mode";
  const triggerId =
    accountOpen && !mobile ? "account-button" : "toggle-sidebar";
  const dismiss = () => {
    setWorkspacePanel(null);
    requestAnimationFrame(() => document.getElementById(triggerId)?.focus());
  };

  useEffect(() => {
    if (!open) return;
    const panel = overlay.current;
    const trigger = document.getElementById(triggerId);
    panel.querySelector("section:not([hidden]) button")?.focus();

    const keydown = (event) => {
      if (event.defaultPrevented || document.querySelector("dialog[open]"))
        return;
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
      }
      if (event.key !== "Tab" || !mobile) return;
      const controls = [
        ...panel.querySelectorAll("button:not(:disabled)"),
      ].filter((button) => button.getClientRects().length);
      const boundary = event.shiftKey ? controls[0] : controls.at(-1);
      if (document.activeElement === boundary) {
        event.preventDefault();
        (event.shiftKey ? controls.at(-1) : controls[0])?.focus();
      }
    };
    const outside = (event) => {
      if (
        !mobile &&
        !panel.contains(event.target) &&
        !trigger?.contains(event.target)
      )
        setWorkspacePanel((current) =>
          current === workspacePanel ? null : current,
        );
    };
    document.addEventListener("keydown", keydown);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("pointerdown", outside);
    };
  }, [workspacePanel, mobile]);

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
            onClick={() => setWorkspacePanel(historyOpen ? null : "history")}
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
        hidden={!(mobile && open)}
        onClick={dismiss}
      />
      <div
        className={"focus-drawer" + (accountOpen ? " account-drawer" : "")}
        ref={overlay}
        hidden={!open}
        role={mobile ? "dialog" : undefined}
        aria-modal={mobile ? true : undefined}
        aria-label={historyOpen ? "Recent conversations" : "Workspace account"}
      >
        <section
          id="sidebar"
          aria-label="Recent conversations"
          hidden={!historyOpen}
        >
          <div className="focus-drawer-heading">
            <h2>Recent conversations</h2>
            <button
              type="button"
              className="icon-button focus-button"
              aria-label="Close recent conversations"
              onClick={dismiss}
            >
              <Icon name="close" />
            </button>
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
                  dismiss();
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
        </section>

        <section
          id="account-menu"
          aria-label="Workspace account"
          hidden={!accountOpen}
        >
          <div className="focus-drawer-heading">
            <h2 id="identity" title={me.id}>
              {identity}
            </h2>
            <button
              type="button"
              className="icon-button focus-button"
              aria-label="Close account"
              onClick={dismiss}
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
              onClick={() => {
                dismiss();
                openDialog("settings");
              }}
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
              onClick={() => {
                dismiss();
                openDialog("password");
              }}
              disabled={busy}
            >
              Browser password
            </button>
            <button id="theme-toggle" type="button" onClick={toggleTheme}>
              {themeLabel}
            </button>
            <button id="sign-out" type="button" onClick={signOut}>
              Sign out
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
