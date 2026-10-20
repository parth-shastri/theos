import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";

export default function WorkspaceActions() {
  const { busy, openDialog, theme, toggleTheme } = useWorkspace();
  const label = "Switch to " + (theme === "dark" ? "light" : "dark") + " mode";
  return (
    <div className="header-actions">
      <button
        id="generation-button"
        aria-label="Settings"
        aria-haspopup="dialog"
        aria-controls="generation-dialog"
        disabled={busy}
        onClick={() => openDialog("settings")}
      >
        <Icon name="settings" />
        <span className="settings-label">Settings</span>
      </button>
      <button
        id="theme-toggle"
        className="icon-button"
        aria-label={label}
        title={label}
        onClick={toggleTheme}
      >
        <Icon name={theme === "dark" ? "sun" : "moon"} />
      </button>
    </div>
  );
}
