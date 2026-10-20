"use client";

import { useEffect } from "react";
import { mountWorkspace } from "../runtime/workspace";
import VoiceAmbience from "./VoiceAmbience";
import SignIn from "./SignIn";
import WorkspaceHeader from "./WorkspaceHeader";
import Sidebar from "./Sidebar";
import Conversation from "./Conversation";
import Activity from "./Activity";
import Connections from "./Connections";
import Tools from "./Tools";
import Dialogs from "./Dialogs";

export default function Workspace({ agentName }) {
  useEffect(() => mountWorkspace(), []);
  return (
    <>
      <VoiceAmbience />
      <SignIn agentName={agentName} />
      <div id="workspace" className="workspace" hidden>
        <WorkspaceHeader agentName={agentName} />
        <Sidebar agentName={agentName} />
        <main>
          <Conversation />
          <Activity />
          <Connections />
          <Tools />
        </main>
      </div>
      <Dialogs />
    </>
  );
}
