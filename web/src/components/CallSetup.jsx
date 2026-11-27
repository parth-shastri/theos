import { useEffect, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";

export default function CallSetup({ calling, busy, action }) {
  const { json } = useWorkspace();
  const [preferences, setPreferences] = useState({
    reminders: false,
    approvals: false,
  });
  useEffect(() => {
    if (calling?.status === "ready")
      setPreferences({
        reminders: calling.reminders,
        approvals: calling.approvals,
      });
  }, [calling?.status, calling?.reminders, calling?.approvals]);
  if (!calling?.configured) return null;
  const state = calling.status;
  const test = calling.test_status;
  const waiting = ["pending", "sending", "accepted"].includes(test);
  const heard = ["completed", "uncertain"].includes(test);
  const request = (step, body = {}) =>
    action(() => json(`/api/calling/${step}`, { method: "POST", body }));
  const change = (name, value) => {
    const previous = preferences;
    const next = { ...preferences, [name]: value };
    setPreferences(next);
    if (state === "ready")
      action(async () => {
        try {
          await json("/api/calling/preferences", {
            method: "POST",
            body: next,
          });
        } catch (error) {
          setPreferences(previous);
          throw error;
        }
      });
  };
  let telegramLink = "";
  try {
    const url = new URL(calling.url);
    if (url.origin === "https://t.me" && !url.username && !url.password)
      telegramLink = url.href;
  } catch {}
  return (
    <section className="call-setup" aria-labelledby="call-setup-title">
      <div className="call-setup-heading">
        <Icon name="phone" />
        <h2 id="call-setup-title">Telegram calls</h2>
        <span className="cost-label">
          {state === "ready" ? "Connected" : "Optional"}
        </span>
      </div>
      <p>
        Hear reminders and approval alerts in Theos’s voice. Calls reach your
        own Telegram account. Review approvals in Theos.
      </p>
      {["disconnected", "disabled", "expired"].includes(state) && (
        <>
          {state === "expired" && (
            <p>
              The verification link expired. Connect again to get a new link.
            </p>
          )}
          <button
            className="primary"
            disabled={busy}
            onClick={() => request("connect")}
          >
            Connect Telegram calls
          </button>
        </>
      )}
      {state === "waiting" && (
        <>
          <p>
            Open Theos calling in Telegram and send the prepared verification
            message. Then return here. The link expires in 10 minutes.
          </p>
          <div className="call-setup-actions">
            {telegramLink && (
              <a
                className="connection-link"
                href={telegramLink}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Theos calling <Icon name="arrowUpRight" />
              </a>
            )}
            <button
              className="soft-button"
              disabled={busy}
              onClick={() => action(async () => {})}
            >
              Check connection
            </button>
            <button
              className="soft-button"
              disabled={busy}
              onClick={() => request("disconnect")}
            >
              Cancel setup
            </button>
          </div>
        </>
      )}
      {state === "linked" && (
        <>
          <p>
            {test
              ? waiting
                ? "Answer the Telegram test call, then confirm the audio below."
                : "If you heard Theos clearly, confirm below. Otherwise end any open call and try the test again."
              : "Your Telegram account is verified. Try one short call before enabling alerts."}
          </p>
          {!test && (
            <button
              className="primary"
              disabled={busy}
              onClick={() => request("test")}
            >
              Call me for the test
            </button>
          )}
          {test && (
            <div className="call-setup-actions">
              <button
                className="primary"
                disabled={busy || !heard}
                onClick={() => request("confirm", preferences)}
              >
                I heard the message — enable calls
              </button>
              <button
                className="soft-button"
                disabled={busy || waiting}
                onClick={() =>
                  action(async () => {
                    await json("/api/calling/retry", {
                      method: "POST",
                      body: {},
                    });
                    await json("/api/calling/test", {
                      method: "POST",
                      body: {},
                    });
                  })
                }
              >
                Try test again
              </button>
            </div>
          )}
        </>
      )}
      {(state === "ready" || (state === "linked" && test)) && (
        <fieldset className="call-setup-preferences" disabled={busy}>
          <legend>When should Theos call?</legend>
          <label>
            <input
              type="checkbox"
              checked={preferences.reminders}
              onChange={(event) => change("reminders", event.target.checked)}
            />
            Call for reminders
          </label>
          <label>
            <input
              type="checkbox"
              checked={preferences.approvals}
              onChange={(event) => change("approvals", event.target.checked)}
            />
            Call when an approval waits for two minutes
          </label>
          <p>
            Written notifications stay available. You can change these choices
            anytime.
          </p>
        </fieldset>
      )}
      {["ready", "linked"].includes(state) && (
        <button
          className="soft-button"
          disabled={busy}
          onClick={() => request("disconnect")}
        >
          {state === "ready" ? "Disconnect calls" : "Cancel setup"}
        </button>
      )}
      {calling.error && (
        <p className="error" role="alert">
          {calling.error}
        </p>
      )}
    </section>
  );
}
