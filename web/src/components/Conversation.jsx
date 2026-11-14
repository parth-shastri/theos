"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Glass } from "./Primitives";
import { Approvals, MessageList } from "./Messages";
import Composer from "./Composer";

export function ConversationActions() {
  const {
    busy,
    chat,
    view,
    workspacePanel,
    openDialog,
    resume,
    reset,
    perform,
  } = useWorkspace();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const click = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("click", click);
    return () => document.removeEventListener("click", click);
  }, [open]);
  useEffect(() => setOpen(false), [busy, view, workspacePanel]);
  return (
    <details
      id="conversation-actions"
      className="conversation-actions"
      open={open}
      ref={ref}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        event.preventDefault();
        setOpen(false);
        ref.current.querySelector("summary").focus();
      }}
    >
      <summary
        aria-label="Conversation actions"
        title="Conversation actions"
        onClick={(event) => {
          event.preventDefault();
          setOpen(!open);
        }}
      >
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="1.75" />
          <circle cx="12" cy="12" r="1.75" />
          <circle cx="19" cy="12" r="1.75" />
        </svg>
      </summary>
      <Glass
        className="conversation-menu"
        onClick={(event) => {
          if (event.target.closest("button")) setOpen(false);
        }}
      >
        <p id="conversation-cost" className="cost-label">
          {chat.id ? "Conversation cost: " + formatCost(chat.usage) : ""}
        </p>
        <button
          id="research-button"
          type="button"
          aria-haspopup="dialog"
          aria-controls="research-dialog"
          onClick={() => openDialog("research")}
        >
          Saved research
        </button>
        <button
          id="resume"
          type="button"
          hidden={view !== "chat-view"}
          disabled={busy}
          onClick={() => perform(resume)}
        >
          Resume conversation
        </button>
        <button
          id="reset"
          type="button"
          hidden={view !== "chat-view"}
          disabled={busy}
          onClick={() => perform(reset)}
        >
          Reset conversation
        </button>
      </Glass>
    </details>
  );
}
export default function Conversation() {
  const { chat, view } = useWorkspace();
  const messages = useRef(null),
    wrap = useRef(null),
    chatView = useRef(null);
  const follow = useRef(true);
  const scroll = () => {
    if (follow.current && messages.current)
      messages.current.scrollTop = messages.current.scrollHeight;
  };
  useLayoutEffect(() => {
    follow.current = true;
    scroll();
  }, [chat.id, chat.revision]);
  useLayoutEffect(() => {
    if (chat.busy) {
      follow.current = true;
      scroll();
    }
  }, [chat.busy]);
  useLayoutEffect(scroll, [chat.entries]);
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      const height = wrap.current?.getBoundingClientRect().height;
      if (!height) return;
      const composer = wrap.current.querySelector("#composer");
      const space =
        composer.getBoundingClientRect().top -
        chatView.current.getBoundingClientRect().top -
        12;
      composer.style.setProperty(
        "--composer-menu-space",
        Math.max(44, Math.floor(space)) + "px",
      );
      scroll();
    });
    observer.observe(wrap.current);
    observer.observe(chatView.current);
    return () => {
      observer.disconnect();
    };
  }, []);
  return (
    <section
      id="chat-view"
      className="chat-view"
      hidden={view !== "chat-view"}
      ref={chatView}
      aria-labelledby="session-title"
    >
      <MessageList
        scrollRef={messages}
        onScroll={() => {
          const element = messages.current;
          follow.current =
            element.scrollHeight - element.scrollTop - element.clientHeight <
            80;
        }}
      />
      <div className="composer-wrap" ref={wrap}>
        <Approvals />
        <Composer />
      </div>
    </section>
  );
}
