import { useEffect, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";

export default function GitHubNotifications({ settings, busy, action }) {
  const { json } = useWorkspace();
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
      {settings.items?.length > 0 && (
        <ul className="github-notification-list">
          {settings.items.map((item) => (
            <li key={item.id} className={item.read ? "is-read" : ""}>
              <a href={item.url} target="_blank" rel="noopener noreferrer">
                {item.text}
              </a>
              {!item.read && (
                <button
                  className="soft-button"
                  disabled={busy}
                  onClick={() =>
                    action(() =>
                      json(
                        `/api/connections/github/notifications/${encodeURIComponent(item.id)}/read`,
                        { method: "POST" },
                      ),
                    )
                  }
                >
                  Mark read
                </button>
              )}
              {item.telegram === "uncertain" && (
                <span className="cost-label">
                  Telegram delivery needs review.
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
