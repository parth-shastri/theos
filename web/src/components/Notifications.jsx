import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";
import PanelHeading from "./PanelHeading";

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
  const { view, navigate, json, me } = useWorkspace();
  const active = view === "notifications-view";
  const [filter, setFilter] = useState("all");
  const [history, setHistory] = useState({ items: [], next_offset: null });
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const historyRequest = useRef(0);
  const { items, unread, loading, busy, error, lastBatch, refresh, change } =
    inbox;

  const loadHistory = useCallback(
    async (offset = 0) => {
      const request = ++historyRequest.current;
      setHistoryLoading(true);
      setHistoryError("");
      try {
        const result = await json(path + "/history?offset=" + offset);
        if (request !== historyRequest.current) return;
        setHistory((current) =>
          offset
            ? {
                items: [...current.items, ...result.items],
                next_offset: result.next_offset,
              }
            : result,
        );
      } catch (error) {
        if (request === historyRequest.current && error.name !== "AbortError")
          setHistoryError("Could not load notification history.");
      } finally {
        if (request === historyRequest.current) setHistoryLoading(false);
      }
    },
    [json],
  );

  useEffect(() => {
    if (!active || !me) return;
    setFilter("all");
    setHistory({ items: [], next_offset: null });
    loadHistory();
    refresh();
    requestAnimationFrame(() =>
      document.getElementById("notifications-title")?.focus(),
    );
    return () => {
      historyRequest.current++;
    };
  }, [active, me?.id, loadHistory, refresh]);

  async function update(notice, undo = false) {
    await change(notice, undo);
    await loadHistory();
  }

  const displayed = filter === "all" ? history.items : items;
  const listLoading = filter === "all" ? historyLoading : loading;
  const listError = filter === "all" ? historyError : error;

  return (
    <section
      id="notifications-view"
      className="workspace-panel notifications-page"
      aria-labelledby="notifications-title"
      hidden={!active}
    >
      <PanelHeading active={active}>
        <div>
          <h1 id="notifications-title" tabIndex={-1}>
            Notifications
          </h1>
          <div className="panel-header-subtext">
            <span className="cost-label">
              Reminders and connected account alerts.
            </span>
          </div>
        </div>
        <button
          id="back-notifications"
          type="button"
          className="panel-back"
          aria-label="Back to chat"
          title="Back to chat"
          onClick={() => navigate("chat-view")}
        >
          <Icon name="back" />
          <span>Back to chat</span>
        </button>
      </PanelHeading>
      <div className="notifications-page-content">
        <p className="notifications-intro">
          Review your notifications here. Dismissed alerts remain under All for
          later reference.
        </p>
        <div className="notifications-tools">
          <span role="status">{loading ? "Loading…" : unread + " unread"}</span>
          <div className="notifications-actions">
            <button
              type="button"
              className="notification-action"
              disabled={busy || historyLoading}
              onClick={() => {
                refresh();
                loadHistory();
              }}
            >
              Refresh
            </button>
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
        </div>
        <div
          className="notification-filters"
          role="group"
          aria-label="Show notifications"
        >
          <button
            type="button"
            aria-pressed={filter === "all"}
            onClick={() => setFilter("all")}
          >
            All
          </button>
          <button
            type="button"
            aria-pressed={filter === "unread"}
            onClick={() => setFilter("unread")}
          >
            Unread
          </button>
        </div>
        {(error || historyError) && (
          <div className="notifications-error">
            <span role="alert" className="error">
              {error || historyError}
            </span>
            <button
              type="button"
              className="notification-action"
              disabled={busy || historyLoading}
              onClick={() => {
                refresh();
                loadHistory();
              }}
            >
              Retry
            </button>
          </div>
        )}
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
        <div className="notification-list" aria-busy={busy || listLoading}>
          {[...groupNotices(displayed)].map(([key, group]) => (
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
                  const noticeUnread =
                    filter === "unread" || Boolean(notice.unread);
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
                      {noticeUnread ? (
                        <button
                          type="button"
                          className="icon-button focus-button"
                          aria-label={
                            "Dismiss " +
                            (group.workflow
                              ? "run #" + workflowRun(notice)
                              : notice.text)
                          }
                          title="Dismiss notification"
                          disabled={busy}
                          onClick={() =>
                            update({ id: notice.id, source: notice.source })
                          }
                        >
                          <Icon name="close" />
                        </button>
                      ) : (
                        <span className="notification-state">Read</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {listLoading && !displayed.length && (
            <p className="notifications-empty">Loading notifications…</p>
          )}
          {!listLoading && !listError && !displayed.length && (
            <p className="notifications-empty">
              {filter === "all"
                ? "No notifications yet."
                : "You’re all caught up."}
            </p>
          )}
          {filter === "unread" && unread > items.length && (
            <p className="notifications-empty">
              Showing the latest {items.length} notifications.
            </p>
          )}
        </div>
        {filter === "all" && history.next_offset !== null && (
          <button
            type="button"
            className="soft-button notifications-load-more"
            disabled={historyLoading}
            onClick={() => loadHistory(history.next_offset)}
          >
            {historyLoading ? "Loading…" : "Load older"}
          </button>
        )}
      </div>
    </section>
  );
}
