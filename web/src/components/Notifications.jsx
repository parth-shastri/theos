import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";

const emptyInbox = { items: [], unread: 0 };
const path = "/api/notifications/browser";
const noticeKey = ({ id, source }) => source + ":" + id;
const dateFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

export function useNotifications(owner) {
  const { json } = useWorkspace();
  const [inbox, setInbox] = useState(null);
  const [lastBatch, setLastBatch] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lifetime = useRef(null);
  const request = useRef(null);
  const changing = useRef(false);

  const refresh = useCallback(async () => {
    if (
      !lifetime.current ||
      lifetime.current.signal.aborted ||
      changing.current
    )
      return;
    request.current?.abort();
    const active = new AbortController();
    request.current = active;
    try {
      const result = await json(path, { signal: active.signal });
      if (!active.signal.aborted) {
        setInbox(result);
        setError("");
      }
    } catch (error) {
      if (!active.signal.aborted && error.name !== "AbortError")
        setError("Could not load notifications.");
    }
  }, [json]);

  useEffect(() => {
    setInbox(null);
    setLastBatch(null);
    setError("");
    setBusy(false);
    changing.current = false;
    if (!owner) return;
    const account = new AbortController();
    lifetime.current = account;
    refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 15000);
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      account.abort();
      request.current?.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [owner, refresh]);

  async function change(notice, undo = false) {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted || changing.current) return;
    changing.current = true;
    request.current?.abort();
    setBusy(true);
    setError("");
    try {
      if (undo) {
        const result = await json(path + "/dismiss/" + lastBatch.id, {
          method: "DELETE",
          signal,
        });
        if (signal.aborted) return;
        setInbox(result);
        setLastBatch(null);
      } else {
        const { batch, ...result } = await json(path + "/dismiss", {
          method: "POST",
          body: { notice },
          signal,
        });
        if (signal.aborted) return;
        setInbox(result);
        if (batch) setLastBatch({ id: batch, single: notice !== null });
      }
    } catch (error) {
      if (!signal.aborted && error.name !== "AbortError")
        setError("Could not update notifications. Please try again.");
    } finally {
      if (!signal.aborted) {
        changing.current = false;
        setBusy(false);
      }
    }
  }

  return {
    ...(inbox ?? emptyInbox),
    loading: !inbox && !error,
    busy,
    error,
    lastBatch,
    refresh,
    change,
  };
}

function workflowRun(notice) {
  if (notice.source !== "github") return null;
  return /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/actions\/runs\/(\d+)$/.exec(
    notice.url,
  )?.[1];
}

function groupNotices(items) {
  const groups = new Map();
  for (const notice of items) {
    const run = workflowRun(notice);
    const key = run ? "workflow:" + notice.text : noticeKey(notice);
    if (!groups.has(key))
      groups.set(key, { notices: [], workflow: Boolean(run) });
    groups.get(key).notices.push(notice);
  }
  return groups;
}

export default function Notifications({ inbox }) {
  const reduceMotion = useReducedMotion();
  const { workspacePanel, setWorkspacePanel } = useWorkspace();
  const open = workspacePanel === "notifications";
  const closeButton = useRef(null);
  const panel = useRef(null);
  const { items, unread, loading, busy, error, lastBatch, refresh, change } =
    inbox;

  const close = () => {
    setWorkspacePanel(null);
    document.getElementById("notifications-button")?.focus();
  };

  useEffect(() => {
    if (!open) return;
    closeButton.current.focus();
    refresh();
    const onKey = (event) => {
      if (
        event.key === "Escape" &&
        !event.defaultPrevented &&
        !document.querySelector("dialog[open]")
      ) {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, refresh]);

  async function update(notice, undo = false) {
    await change(notice, undo);
    requestAnimationFrame(() => {
      if (panel.current?.hidden || document.activeElement !== document.body)
        return;
      panel.current?.querySelector(".notifications-undo button")?.focus();
      if (document.activeElement === document.body)
        closeButton.current?.focus();
    });
  }

  return (
    <section
      id="notifications-inbox"
      className="notifications-inbox"
      aria-labelledby="notifications-title"
      hidden={!open}
      ref={panel}
    >
      <div className="focus-drawer-heading">
        <h2 id="notifications-title">Notifications</h2>
        <button
          type="button"
          className="icon-button focus-button"
          ref={closeButton}
          aria-label="Close notifications"
          onClick={close}
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="notifications-tools">
        <span role="status">{loading ? "Loading…" : `${unread} unread`}</span>
        {unread > 0 && (
          <button
            type="button"
            className="notification-action"
            disabled={busy}
            onClick={() => update(null)}
          >
            Dismiss all
          </button>
        )}
      </div>
      {error && (
        <div className="notifications-tools">
          <span role="alert" className="error">
            {error}
          </span>
          <button
            type="button"
            className="notification-action"
            disabled={busy}
            onClick={refresh}
          >
            Retry
          </button>
        </div>
      )}
      <div className="notification-list" aria-busy={busy}>
        {[...groupNotices(items)].map(([key, group]) => (
          <div className="notification-group" key={key}>
            {group.workflow && (
              <div className="notification-group-heading">
                <span className="notification-source-icon">
                  <Icon name="branch" />
                </span>
                <div>
                  <strong>{group.notices[0].text}</strong>
                  <span>GitHub</span>
                </div>
              </div>
            )}
            <ul>
              {group.notices.map((notice) => {
                const date = new Date(notice.created * 1000);
                return (
                  <li className="notification-row" key={noticeKey(notice)}>
                    <div>
                      {notice.source === "github" ? (
                        <a
                          href={notice.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {group.workflow
                            ? "Run #" + workflowRun(notice)
                            : notice.text}
                        </a>
                      ) : (
                        <strong>{notice.text}</strong>
                      )}
                      <span className="notification-date">
                        {!group.workflow &&
                          (notice.source === "github"
                            ? "GitHub · "
                            : "Reminder · ")}
                        <time dateTime={date.toISOString()}>
                          {dateFormat.format(date)}
                        </time>
                      </span>
                    </div>
                    <button
                      type="button"
                      className="icon-button focus-button"
                      aria-label={`Dismiss ${group.workflow ? "run #" + workflowRun(notice) : notice.text}`}
                      title="Dismiss notification"
                      disabled={busy}
                      onClick={() =>
                        update({ id: notice.id, source: notice.source })
                      }
                    >
                      <Icon name="close" />
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
        {!loading && !error && !unread && (
          <p className="notifications-empty">You’re all caught up.</p>
        )}
        {unread > items.length && (
          <p className="notifications-empty">
            Showing the latest {items.length} notifications.
          </p>
        )}
      </div>
      {lastBatch && (
        <motion.div
          className="notifications-undo"
          initial={reduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18 }}
        >
          <span role="status">
            {lastBatch.single
              ? "Notification dismissed."
              : "Notifications dismissed."}
          </span>
          <button
            type="button"
            className="notification-action"
            disabled={busy}
            onClick={() => update(null, true)}
          >
            Undo
          </button>
        </motion.div>
      )}
    </section>
  );
}
