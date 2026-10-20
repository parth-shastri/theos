import { createPortal } from "react-dom";
import { useWorkspace } from "../state/WorkspaceContext";
import { Glass } from "./Primitives";
import WorkspaceActions from "./WorkspaceActions";

export default function PanelHeading({
  active,
  glass = false,
  className = "",
  children,
  ...props
}) {
  const { panelHeadingHost } = useWorkspace();
  const pinned = panelHeadingHost;
  const Surface = glass || pinned ? Glass : "div";
  const heading = (
    <Surface
      {...props}
      className={
        "panel-heading" +
        (glass || pinned ? " liquid-panel" : "") +
        (className ? " " + className : "")
      }
      hidden={!active}
    >
      {children}
      {active && <WorkspaceActions />}
    </Surface>
  );
  return pinned ? createPortal(heading, panelHeadingHost) : heading;
}
