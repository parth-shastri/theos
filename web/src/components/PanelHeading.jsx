import { createPortal } from "react-dom";
import { useWorkspace } from "../state/WorkspaceContext";
import { Glass } from "./Primitives";

export default function PanelHeading({
  active,
  glass = false,
  className = "",
  children,
}) {
  const { mobile, panelHeadingHost } = useWorkspace();
  const pinned = mobile && panelHeadingHost;
  const Surface = glass || pinned ? Glass : "div";
  const heading = (
    <Surface
      className={
        "panel-heading" +
        (glass || pinned ? " liquid-panel" : "") +
        (className ? " " + className : "")
      }
      hidden={!active}
    >
      {children}
    </Surface>
  );
  return pinned ? createPortal(heading, panelHeadingHost) : heading;
}
