import { useEffect, useId, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";

export default function PasswordSettings({ action }) {
  const { json } = useWorkspace();
  const id = useId();
  const [settings, setSettings] = useState(null);
  const enabled = settings?.enabled;
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    json("/api/auth/password", { signal: controller.signal })
      .then(setSettings)
      .catch((error) => {
        if (error.name !== "AbortError")
          setFeedback({ error: true, text: error.message });
      });
    return () => controller.abort();
  }, [json]);

  const update = async (method, body) => {
    if (busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      const result = await json("/api/auth/password", { method, body });
      setSettings(result);
      setFeedback({
        text: result.enabled ? "Password saved." : "Password removed.",
      });
    } catch (error) {
      if (error.name !== "AbortError")
        setFeedback({ error: true, text: error.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="password-settings"
      method="post"
      onSubmit={(event) => {
        event.preventDefault();
        if (busy || !settings) return;
        const form = event.currentTarget;
        const data = new FormData(form);
        form.reset();
        void update("POST", {
          password: data.get("password"),
          confirmation: data.get("confirmation"),
        });
      }}
    >
      <p>Use your account ID and password to sign in on another device.</p>
      <label htmlFor={id + "-account"}>Account ID</label>
      <input
        id={id + "-account"}
        name="username"
        autoComplete="username"
        value={settings?.account || ""}
        readOnly
      />
      <label htmlFor={id + "-password"}>New password</label>
      <input
        id={id + "-password"}
        name="password"
        type="password"
        autoComplete="new-password"
        aria-describedby={id + "-rules"}
        required
        disabled={busy || !settings}
      />
      <small id={id + "-rules"}>
        Use 15 to 128 characters. A few unrelated words can make a strong
        password.
      </small>
      <label htmlFor={id + "-confirmation"}>Confirm password</label>
      <input
        id={id + "-confirmation"}
        name="confirmation"
        type="password"
        autoComplete="new-password"
        required
        disabled={busy || !settings}
      />
      <div className="password-actions">
        <button className="primary" type="submit" disabled={busy || !settings}>
          {action === "reset"
            ? "Reset password"
            : enabled
              ? "Change password"
              : "Set password"}
        </button>
        {enabled && !action && (
          <button
            type="button"
            disabled={busy}
            onClick={(event) => {
              event.currentTarget.form.reset();
              void update("DELETE");
            }}
          >
            Remove password
          </button>
        )}
      </div>
      {feedback && (
        <p
          role={feedback.error ? "alert" : "status"}
          className={feedback.error ? "error" : undefined}
        >
          {feedback.text}
        </p>
      )}
    </form>
  );
}
