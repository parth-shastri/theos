import { useWorkspace } from "../state/WorkspaceContext";
import { ConversationActions } from "./Conversation";
import { Icon } from "./Primitives";

export default function WorkspaceHeader({ unread }) {
  const {
    agentName,
    chat,
    view,
    mobile,
    sidebarOpen,
    setSidebarOpen,
    workspacePanel,
    setWorkspacePanel,
    setPanelHeadingHost,
  } = useWorkspace();
  const inChat = view === "chat-view";
  const inboxOpen = workspacePanel === "notifications";

  return (
    <header className="focus-header" inert={mobile && sidebarOpen}>
      {mobile && (
        <button
          id="toggle-sidebar"
          type="button"
          className="icon-button focus-button"
          aria-label="Toggle conversation sidebar"
          aria-expanded={sidebarOpen}
          aria-controls="sidebar"
          title="Conversations"
          onClick={() => {
            setWorkspacePanel(null);
            setSidebarOpen((value) => !value);
          }}
        >
          <Icon name="sidebar" />
        </button>
      )}
      {inChat ? (
        <>
          <h1 id="session-title" title={chat.title}>
            {chat.title}
          </h1>
          <div className="focus-header-actions">
            <button
              id="notifications-button"
              type="button"
              className="icon-button focus-button"
              aria-label={
                unread ? `Notifications, ${unread} unread` : "Notifications"
              }
              aria-expanded={inboxOpen}
              aria-controls="notifications-inbox"
              title="Notifications"
              onClick={() =>
                setWorkspacePanel(inboxOpen ? null : "notifications")
              }
            >
              <Icon name="bell" />
              {unread > 0 && (
                <span className="notification-count" aria-hidden="true">
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </button>
            {(!mobile || !inboxOpen) && <ConversationActions />}
          </div>
        </>
      ) : mobile ? (
        <div className="focus-panel-heading" ref={setPanelHeadingHost} />
      ) : (
        <span className="focus-workspace-name">{agentName}</span>
      )}
    </header>
  );
}
