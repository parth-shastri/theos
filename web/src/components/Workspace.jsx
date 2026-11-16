"use client";
import { WorkspaceProvider, useWorkspace } from "../state/WorkspaceContext";
import { GlassProvider } from "./Primitives";
import VoiceAmbience from "./VoiceAmbience";
import SignIn from "./SignIn";
import WorkspaceHeader from "./WorkspaceHeader";
import Sidebar from "./Sidebar";
import Notifications, { useNotifications } from "./Notifications";
import Conversation from "./Conversation";
import Activity from "./Activity";
import Connections from "./Connections";
import Tools from "./Tools";
import Dialogs from "./Dialogs";
import { useVisualViewport } from "../hooks/useVisualViewport";
function WorkspaceContents() {
  useVisualViewport();
  const { me, mobile, sidebarOpen, view, setDesktopPanelHeadingHost } =
    useWorkspace();
  const inbox = useNotifications(me?.id);
  const drawerOpen = mobile && sidebarOpen;
  return (
    <GlassProvider>
      <VoiceAmbience />
      <SignIn />
      <div
        id="workspace"
        className={
          "workspace focus-workspace" + (sidebarOpen ? " sidebar-open" : "")
        }
        hidden={!me}
      >
        <WorkspaceHeader unread={inbox.unread} />
        {me && <Sidebar />}
        <main inert={drawerOpen}>
          <div
            className="panel-toolbar-host"
            ref={setDesktopPanelHeadingHost}
            hidden={view === "chat-view"}
          />
          <Conversation />
          <Activity />
          <Connections />
          <Tools />
          <Notifications inbox={inbox} />
        </main>
      </div>
      <Dialogs />
    </GlassProvider>
  );
}
export default function Workspace({ agentName }) {
  return (
    <WorkspaceProvider agentName={agentName}>
      <WorkspaceContents />
    </WorkspaceProvider>
  );
}
