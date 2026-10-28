import { createPortal } from "react-dom";
import { useWorkspace } from "../state/WorkspaceContext";
import { Glass } from "./Primitives";

export default function PanelHeading({
  active,
  glass = false,
  className = "",
  children,
}) {
  const { mobile, panelHeadingHost, desktopPanelHeadingHost } = useWorkspace();
  const host = mobile ? panelHeadingHost : desktopPanelHeadingHost;
  const Surface = mobile && (glass || host) ? Glass : "div";
  const heading = (
    <Surface
      className={
        (mobile ? "panel-heading" : "workspace-toolbar panel-tab-toolbar") +
        (mobile && (glass || host) ? " liquid-panel" : "") +
        (className ? " " + className : "")
      }
      hidden={!active}
    >
      {children}
    </Surface>
  );
  return host ? createPortal(heading, host) : heading;
}
