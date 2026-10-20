import { useWorkspace } from "../state/WorkspaceContext";
import { Glass, Icon } from "./Primitives";
export default function WorkspaceHeader() {
  const { sidebarOpen, setSidebarOpen, mobile, setPanelHeadingHost } =
    useWorkspace();
  const toggle = () => {
    setSidebarOpen(!sidebarOpen);
    if (!sidebarOpen && mobile)
      requestAnimationFrame(() =>
        document.getElementById("new-session")?.focus(),
      );
  };
  return (
    <>
      <Glass as="header" className="app-header">
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
      </Glass>
      <div
        className="page-header"
        ref={setPanelHeadingHost}
        hidden={mobile && sidebarOpen}
        inert={mobile && sidebarOpen}
      />
    </>
  );
}
