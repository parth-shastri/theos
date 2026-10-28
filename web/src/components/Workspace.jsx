"use client";
import { WorkspaceProvider, useWorkspace } from "../state/WorkspaceContext";
import { GlassProvider } from "./Primitives";
import VoiceAmbience from "./VoiceAmbience";
import SignIn from "./SignIn";
import WorkspaceHeader from "./WorkspaceHeader";
import Sidebar from "./Sidebar";
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
  return (
    <GlassProvider>
      <VoiceAmbience />
      <SignIn />
      <div
        id="workspace"
        className={"workspace" + (sidebarOpen ? "" : " sidebar-collapsed")}
        hidden={!me}
      >
        <WorkspaceHeader />
        <Sidebar />
        <main inert={mobile && sidebarOpen}>
          <div
            className="panel-toolbar-host"
            ref={setDesktopPanelHeadingHost}
            hidden={view === "chat-view"}
          />
          <Conversation />
          <Activity />
          <Connections />
          <Tools />
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
