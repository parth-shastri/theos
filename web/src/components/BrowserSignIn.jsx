import { useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Glass } from "./Primitives";

export default function BrowserSignIn({ configured }) {
  const { json } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [text, setText] = useState("");
  const [image, setImage] = useState("");
  const [snapshot, setSnapshot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const pending = useRef(false);

  async function act(body) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setNotice("");
    try {
      const result = await json("/api/connections/browser/action", {
        method: "POST",
        body,
      });
      setImage(result.image);
      setSnapshot(result.snapshot);
      if (!result.success)
        setNotice(
          "The browser could not complete that action. Refresh to check the page.",
        );
    } catch (error) {
      setNotice(error.message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return (
    <Glass
      as="article"
      className="connection-card liquid-panel browser-sign-in"
    >
      <div className="connection-heading">
        <h3>Browser sign-in</h3>
        <button
          className="soft-button"
          disabled={!configured || busy}
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          {open ? "Close controls" : "Open browser"}
        </button>
      </div>
      <p>
        Sign in to websites once. Theos reuses your private browser across
        conversations. Closing these controls keeps your login.
      </p>
      {open && (
        <div className="browser-controls" aria-busy={busy}>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              act({ action: "open", url });
            }}
          >
            <label htmlFor="browser-url">Website address</label>
            <div className="browser-control-row">
              <input
                id="browser-url"
                type="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com"
                required
                disabled={busy}
              />
              <button className="primary" disabled={busy}>
                Go
              </button>
              <button
                className="soft-button"
                type="button"
                disabled={busy}
                onClick={() => act({ action: "refresh" })}
              >
                Refresh
              </button>
            </div>
          </form>
          <p>
            Select a field in the page below. Use the private input to enter a
            password or verification code.
          </p>
          {image && (
            <img
              className="browser-screen"
              src={image}
              alt="Your private browser page. Select a field to focus it."
              tabIndex={0}
              onClick={(event) => {
                if (busy) return;
                const rectangle = event.currentTarget.getBoundingClientRect();
                act({
                  action: "click",
                  x: Math.floor(
                    ((event.clientX - rectangle.left) *
                      event.currentTarget.naturalWidth) /
                      rectangle.width,
                  ),
                  y: Math.floor(
                    ((event.clientY - rectangle.top) *
                      event.currentTarget.naturalHeight) /
                      rectangle.height,
                  ),
                });
              }}
              onKeyDown={(event) => {
                if (
                  [
                    "Enter",
                    "Tab",
                    "Backspace",
                    "Escape",
                    "ArrowUp",
                    "ArrowDown",
                  ].includes(event.key) &&
                  event.key !== "Tab"
                ) {
                  event.preventDefault();
                  act({ action: "press", key: event.key });
                }
              }}
            />
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const value = text;
              setText("");
              act({ action: "type", text: value });
            }}
          >
            <label htmlFor="browser-private-input">Private input</label>
            <div className="browser-control-row">
              <input
                id="browser-private-input"
                type="password"
                autoComplete="off"
                value={text}
                onChange={(event) => setText(event.target.value)}
                disabled={busy}
              />
              <button className="primary" disabled={busy || !text}>
                Type into page
              </button>
            </div>
          </form>
          <div className="browser-control-row">
            <button
              className="soft-button"
              disabled={busy}
              onClick={() => act({ action: "press", key: "Tab" })}
            >
              Next field
            </button>
            <button
              className="soft-button"
              disabled={busy}
              onClick={() => act({ action: "press", key: "Enter" })}
            >
              Press Enter
            </button>
            <button
              className="soft-button"
              disabled={busy}
              onClick={() => act({ action: "scroll", direction: "up" })}
            >
              Scroll up
            </button>
            <button
              className="soft-button"
              disabled={busy}
              onClick={() => act({ action: "scroll", direction: "down" })}
            >
              Scroll down
            </button>
          </div>
          {snapshot && (
            <details>
              <summary>Page controls as text</summary>
              <pre>
                {typeof snapshot === "string"
                  ? snapshot
                  : JSON.stringify(snapshot, null, 2)}
              </pre>
            </details>
          )}
          <button
            className="soft-button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await json("/api/connections/browser/disconnect", {
                  method: "POST",
                });
                setImage("");
                setSnapshot(null);
                setText("");
                setNotice("Saved browser login cleared.");
              } catch (error) {
                setNotice(error.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Clear saved browser login
          </button>
        </div>
      )}
      <p role="status" aria-live="polite">
        {busy ? "Updating browser…" : notice}
      </p>
    </Glass>
  );
}
