import { useEffect, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";

export default function GitHubNotifications({ settings, busy, action }) {
  const { json, navigate } = useWorkspace();
  const [preferences, setPreferences] = useState({
    enabled: settings?.enabled || false,
    telegram: settings?.telegram || false,
  });
  useEffect(() => {
    setPreferences({
      enabled: settings?.enabled || false,
      telegram: settings?.telegram || false,
    });
  }, [settings?.enabled, settings?.telegram]);
  if (!settings) return null;
  const update = (enabled, telegram) => {
    const previous = preferences;
    setPreferences({ enabled, telegram });
    action(async () => {
      try {
        await json("/api/connections/github/notifications", {
          method: "PUT",
          body: { enabled, telegram },
        });
      } catch (error) {
        setPreferences(previous);
        throw error;
      }
    });
  };
  return (
    <section
      className="github-notifications"
      aria-label="GitHub event notifications"
    >
      <div className="github-notification-heading">
        <h4>Event notifications</h4>
        <span className="cost-label">Only what needs you</span>
      </div>
      <p>
        Direct mentions, assignments, review requests, and failed workflows you
        triggered.
      </p>
      {settings.available ? (
        <>
          <label className="github-notification-toggle">
            <input
              type="checkbox"
              checked={preferences.enabled}
              disabled={busy}
              onChange={(event) =>
                update(event.target.checked, preferences.telegram)
              }
            />
            Notify me in Theos
          </label>
          <label className="github-notification-toggle">
            <input
              type="checkbox"
              checked={preferences.telegram}
              disabled={
                busy || !preferences.enabled || !settings.telegram_available
              }
              onChange={(event) =>
                update(preferences.enabled, event.target.checked)
              }
            />
            Also notify my private Telegram chat
          </label>
          {!settings.telegram_available && (
            <p className="cost-label">
              For Telegram alerts, connect GitHub in your private bot chat and
              send /github_notifications on.
            </p>
          )}
        </>
      ) : (
        <p className="cost-label">Event notifications need operator setup.</p>
      )}
      <button
        type="button"
        className="soft-button github-notification-link"
        onClick={() => navigate("notifications-view")}
      >
        <Icon name="bell" /> View all notifications
      </button>
    </section>
  );
}
