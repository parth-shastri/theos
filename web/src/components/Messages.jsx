"use client";
import {
  createContext,
  memo,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import Markdown, { markdownText } from "./Markdown";
import { Icon } from "./Primitives";

const SpeechContext = createContext(null);
export function SpeechProvider({ children }) {
  const active = useRef(null);
  useEffect(() => {
    const stop = () => active.current?.stop();
    window.addEventListener("pagehide", stop);
    return () => {
      stop();
      window.removeEventListener("pagehide", stop);
    };
  }, []);
  return (
    <SpeechContext.Provider value={active}>{children}</SpeechContext.Provider>
  );
}
function SpeechButton({ source, sessionId, autoPlay }) {
  const { api, json, showError, status } = useWorkspace();
  const active = useContext(SpeechContext);
  const [playback, setPlayback] = useState("ready");
  const player = useRef(null),
    alive = useRef(false),
    lastAutoPlay = useRef(null);
  const text = markdownText(source);
  const tooLong = text.length > 12000;
  useEffect(() => {
    alive.current = true;
    const request = new AbortController();
    const control = {
      request,
      audio: null,
      url: null,
      stop() {
        if (active.current === control) active.current = null;
        if (control.audio) {
          control.audio.pause();
          control.audio.currentTime = 0;
        }
        if (alive.current) setPlayback("ready");
      },
    };
    player.current = control;
    return () => {
      alive.current = false;
      request.abort();
      control.stop();
      if (control.audio) {
        control.audio.onended =
          control.audio.onpause =
          control.audio.onerror =
            null;
        control.audio.removeAttribute("src");
        control.audio.load();
      }
      if (control.url) URL.revokeObjectURL(control.url);
    };
  }, [text, sessionId, active]);
  const play = async () => {
    const control = player.current;
    if (!control || tooLong) return;
    if (active.current === control) return control.stop();
    setPlayback("loading");
    try {
      if (!control.audio) {
        const result = await json("/api/audio/speech", {
          method: "POST",
          body: { text, session_id: sessionId },
          signal: control.request.signal,
        });
        const response = await api("/api/files/" + result.file_id, {
          signal: control.request.signal,
        });
        const blob = await response.blob();
        if (control.request.signal.aborted) return;
        control.url = URL.createObjectURL(blob);
        control.audio = new Audio(control.url);
        control.audio.onended = control.audio.onpause = () => {
          if (control.audio.paused || control.audio.ended) control.stop();
        };
        control.audio.onerror = () => {
          control.stop();
          control.audio.removeAttribute("src");
          control.audio.load();
          control.audio = null;
          URL.revokeObjectURL(control.url);
          control.url = null;
          if (alive.current)
            showError(
              new Error(
                "Audio playback failed. Select Read aloud to try again.",
              ),
            );
        };
      }
      if (control.request.signal.aborted) return;
      active.current?.stop();
      active.current = control;
      setPlayback("playing");
      await control.audio.play();
      if (control.request.signal.aborted || active.current !== control)
        control.stop();
    } catch (error) {
      control.stop();
      if (control.request.signal.aborted) return;
      if (error.name === "NotAllowedError")
        status("Audio is ready. Select Read aloud to listen.");
      else showError(error);
    }
  };
  useEffect(() => {
    if (autoPlay && lastAutoPlay.current !== autoPlay && !tooLong) {
      lastAutoPlay.current = autoPlay;
      play();
    }
  }, [autoPlay]);
  const label =
    playback === "loading"
      ? "Preparing audio"
      : playback === "playing"
        ? "Stop playback"
        : tooLong
          ? "Speech supports replies up to 12,000 characters."
          : "Read aloud";
  return (
    <div className="speech-control">
      <button
        type="button"
        className={
          "icon-button speech-button" +
          (playback === "playing" ? " is-playing" : "")
        }
        disabled={tooLong || playback === "loading"}
        aria-busy={playback === "loading" ? true : undefined}
        aria-label={label}
        title={label}
        onClick={play}
      >
        <Icon
          name={
            playback === "loading"
              ? "loading"
              : playback === "playing"
                ? "stop"
                : "speaker"
          }
        />
      </button>
    </div>
  );
}
function Metadata({ entry }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!entry.streaming) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(timer);
  }, [entry.streaming, entry.started]);
  const display = entry.display || {},
    usage = entry.usage || {};
  const parts = [];
  const tokens = usage.output_tokens;
  const reported =
    tokens > 0 || usage.input_tokens > 0 || usage.total_tokens > 0;
  if (reported && Number.isInteger(tokens) && tokens >= 0)
    parts.push(
      <span
        className="token-count"
        key="tokens"
        title="Output tokens reported by the provider, including reasoning when applicable."
      >
        {tokens.toLocaleString()} tokens
      </span>,
    );
  else if (entry.role === "assistant")
    parts.push(
      <span
        className="token-count"
        key="tokens"
        title="Estimated from streamed text and reasoning. Provider usage may include additional tokens."
      >
        ~
        {Math.ceil(
          ((entry.text || "").length + (entry.reasoning || "").length) / 4,
        ).toLocaleString()}{" "}
        tokens
      </span>,
    );
  const duration = entry.streaming
    ? Math.max(0, now - entry.started)
    : display.duration_ms;
  if (Number.isFinite(duration))
    parts.push(
      <span
        className="generation-time"
        key="duration"
        title="Time spent generating this message."
      >
        {duration < 60000
          ? (duration / 1000).toFixed(1) + "s"
          : Math.floor(duration / 60000) +
            "m " +
            String(Math.floor((duration % 60000) / 1000)).padStart(2, "0") +
            "s"}
      </span>,
    );
  if (Number.isFinite(display.created_at)) {
    const date = new Date(display.created_at * 1000);
    const values = Object.fromEntries(
      new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(date)
        .map((part) => [part.type, part.value]),
    );
    parts.push(
      <time
        key="date"
        dateTime={date.toISOString()}
        title={date.toLocaleString(undefined, {
          dateStyle: "full",
          timeStyle: "long",
        })}
      >
        {values.day +
          " " +
          values.month +
          " " +
          values.year +
          " " +
          values.hour +
          ":" +
          values.minute}
      </time>,
    );
  }
  return (
    <div className="message-meta" hidden={!parts.length}>
      {parts.flatMap((part, index) =>
        index
          ? [
              <span
                className="meta-separator"
                aria-hidden="true"
                key={"separator-" + index}
              >
                ·
              </span>,
              part,
            ]
          : [part],
      )}
    </div>
  );
}
const ChatMessage = memo(function ChatMessage({
  entry,
  agentName,
  sessionId,
  speech,
  autoPlay,
}) {
  return (
    <article
      className={
        "message " + (entry.role === "workspace" ? "system" : entry.role)
      }
    >
      <div className="role">
        {entry.role === "assistant"
          ? agentName
          : entry.role === "workspace"
            ? "Workspace"
            : "You"}
      </div>
      {(entry.reasoning || entry.thinking) && (
        <details
          className={"thinking" + (entry.thinking ? " is-thinking" : "")}
        >
          <summary>
            <span className="thinking-orb" aria-hidden="true" />
            <span className="thinking-label">
              {entry.thinking ? "Thinking…" : "Thinking"}
            </span>
          </summary>
          <Markdown
            className="thinking-body"
            source={entry.reasoning || ""}
            hidden={!entry.reasoning}
          />
        </details>
      )}
      {entry.role === "assistant" ? (
        <Markdown className="body" source={entry.text} />
      ) : (
        <div className="body">
          {entry.text}
          {entry.images
            ?.filter((image) => image.url.startsWith("data:image/"))
            .map((image, index) => (
              <img
                src={image.url}
                alt={image.filename || "Attached image"}
                key={index}
              />
            ))}
        </div>
      )}
      <div className="message-footer">
        {speech &&
          entry.role === "assistant" &&
          !entry.streaming &&
          !!markdownText(entry.text) && (
            <SpeechButton
              source={entry.text}
              sessionId={sessionId}
              autoPlay={autoPlay}
            />
          )}
        <Metadata entry={entry} />
      </div>
    </article>
  );
});
function FileDownload({ entry }) {
  const { api, perform } = useWorkspace();
  const [download, setDownload] = useState(null);
  const anchor = useRef(null);
  useEffect(() => {
    if (!download) return;
    anchor.current.click();
    const timer = setTimeout(() => setDownload(null), 1000);
    return () => {
      clearTimeout(timer);
      URL.revokeObjectURL(download);
    };
  }, [download]);
  return (
    <>
      <button
        onClick={() =>
          perform(async () => {
            const response = await api("/api/files/" + entry.file_id);
            setDownload(URL.createObjectURL(await response.blob()));
          })
        }
      >
        {"↓ " + (entry.name || "Download file")}
      </button>
      {download && (
        <a
          href={download}
          download={entry.name || "file"}
          ref={anchor}
          hidden
        />
      )}
    </>
  );
}
export function MessageList({ scrollRef, onScroll }) {
  const { chat, agentName, me, brand, editDraft, autoPlay } = useWorkspace();
  return (
    <SpeechProvider>
      <div
        id="messages"
        role="log"
        aria-label="Conversation"
        tabIndex={0}
        aria-live="polite"
        ref={scrollRef}
        onScroll={onScroll}
      >
        {!chat.entries.length && (
          <div className="empty">
            <img className="mark" src={brand} alt="" data-brand="" />
            <span className="eyebrow">A little space to think</span>
            <h1>What’s on your mind?</h1>
            <p>
              Ask a question, make a plan, or work through an idea. Your next
              step starts here.
            </p>
            <div className="conversation-starters">
              {[
                ["skills", "Make a plan", "Help me make a plan for "],
                ["search", "Explore a topic", "Help me understand "],
                [
                  "attach",
                  "Work with a file",
                  "Help me with the file I attach. ",
                ],
              ].map(([icon, label, draft]) => (
                <button
                  type="button"
                  key={label}
                  onClick={() => editDraft(draft)}
                >
                  <Icon name={icon} />
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        {chat.entries.map((entry) =>
          entry.kind === "message" ? (
            <ChatMessage
              key={chat.revision + "-" + entry.id}
              entry={entry}
              agentName={agentName}
              sessionId={chat.id}
              speech={me?.voice.tts}
              autoPlay={
                autoPlay?.sessionId === chat.id && entry.id === chat.lastAnswer
                  ? autoPlay.request
                  : null
              }
            />
          ) : entry.kind === "tool" ? (
            <details
              className="tool-activity"
              data-call-id={entry.callId}
              key={chat.revision + "-" + entry.id}
            >
              <summary>
                {entry.name + " · " + entry.status.replaceAll("_", " ")}
              </summary>
              {entry.arguments !== null && (
                <>
                  <strong>Inputs</strong>
                  <pre className="tool-inputs">
                    {JSON.stringify(entry.arguments, null, 2)}
                  </pre>
                </>
              )}
              {entry.content !== null && (
                <>
                  <strong>Result</strong>
                  <pre className="tool-result">{entry.content}</pre>
                </>
              )}
            </details>
          ) : entry.kind === "file" ? (
            <FileDownload entry={entry} key={chat.revision + "-" + entry.id} />
          ) : (
            <div
              className={
                "context-activity" + (entry.active ? " is-organizing" : "")
              }
              role="status"
              aria-live="polite"
              key={chat.revision + "-" + entry.id}
            >
              {entry.text}
            </div>
          ),
        )}
      </div>
    </SpeechProvider>
  );
}
function ReviewField({ field }) {
  const wide = field.kind !== "text" || field.text.includes("\n");
  return (
    <>
      <dt className={wide ? "approval-wide" : undefined}>{field.label}</dt>
      <dd className={wide ? "approval-wide" : undefined}>
        {field.kind === "markdown" ? (
          <Markdown source={field.text} />
        ) : field.kind === "code" ? (
          <pre className="approval-value">{field.text}</pre>
        ) : (
          <div className="approval-value">{field.text}</div>
        )}
        {field.hint && <small className="approval-hint">{field.hint}</small>}
      </dd>
    </>
  );
}
function ApprovalCard({ item }) {
  const { busy, approve } = useWorkspace();
  const groups = [],
    technical = [];
  let group = null,
    technicalGroup = null;
  for (const [index, field] of (item.review || []).entries()) {
    if (field.technical) {
      if (field.group && field.group !== technicalGroup) {
        technicalGroup = field.group;
        technical.push(
          <dt className="approval-group" key={"group-" + index}>
            {field.group}
          </dt>,
        );
      }
      technical.push(<ReviewField key={index} field={field} />);
    } else {
      if (!group || group.name !== field.group) {
        group = { name: field.group, fields: [] };
        groups.push(group);
      }
      group.fields.push(<ReviewField key={index} field={field} />);
    }
  }
  let exact = item.arguments;
  try {
    exact = JSON.stringify(JSON.parse(item.arguments), null, 2);
  } catch {}
  return (
    <article>
      <strong>Approval needed</strong>
      <p className="approval-action">
        {item.label || item.tool.replaceAll("_", " ")}
      </p>
      {groups.map((group, index) => (
        <ReviewGroup group={group} key={index} />
      ))}
      {!!technical.length && (
        <details className="approval-technical">
          <summary>Exact request details</summary>
          <dl className="approval-fields">{technical}</dl>
        </details>
      )}
      <details>
        <summary>Exact tool arguments</summary>
        <pre>{exact}</pre>
      </details>
      <button
        className="primary"
        disabled={busy}
        onClick={() => approve(item, true)}
      >
        Approve
      </button>
      <button disabled={busy} onClick={() => approve(item, false)}>
        Deny
      </button>
    </article>
  );
}
function ReviewGroup({ group }) {
  return (
    <>
      {group.name && <h3 className="approval-group">{group.name}</h3>}
      <dl className="approval-fields">{group.fields}</dl>
    </>
  );
}
export function Approvals() {
  const { chat } = useWorkspace();
  return (
    <div id="approvals">
      {chat.approvals.map((item) => (
        <ApprovalCard item={item} key={item.id} />
      ))}
    </div>
  );
}
