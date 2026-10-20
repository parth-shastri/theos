"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { Glass } from "./Primitives";
import { Approvals, MessageList } from "./Messages";
import Composer from "./Composer";
import PanelHeading from "./PanelHeading";

export function ConversationActions() {
  const { busy, view, openDialog, resume, reset, perform } = useWorkspace();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const click = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false);
    };
    const key = (event) => {
      if (event.key === "Escape" && open) {
        setOpen(false);
        ref.current.querySelector("summary").focus();
      }
    };
    document.addEventListener("click", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("click", click);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  useEffect(() => setOpen(false), [busy, view]);
  return (
    <details
      id="conversation-actions"
      className="conversation-actions"
      open={open}
      ref={ref}
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
        <span className="conversation-actions-label">Conversation actions</span>
      </summary>
      <Glass
        className="conversation-menu"
        onClick={(event) => {
          if (event.target.closest("button")) setOpen(false);
        }}
      >
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
  const { chat, mobile, view, notifications } = useWorkspace();
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
    const viewport = window.visualViewport;
    const fit = () => {
      if (!viewport || viewport.scale !== 1) return;
      document.documentElement.style.setProperty(
        "--viewport-height",
        Math.round(viewport.height) + "px",
      );
      document.documentElement.classList.toggle(
        "keyboard-open",
        innerHeight - viewport.height > 120,
      );
      scroll();
    };
    viewport?.addEventListener("resize", fit);
    fit();
    const observer = new ResizeObserver(() => {
      const height = wrap.current?.getBoundingClientRect().height;
      if (!height) return;
      chatView.current.style.setProperty(
        "--composer-space",
        Math.ceil(height) + "px",
      );
      const composer = wrap.current.querySelector("#composer");
      const space =
        composer.getBoundingClientRect().top -
        chatView.current.closest("main").getBoundingClientRect().top -
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
      viewport?.removeEventListener("resize", fit);
      document.documentElement.classList.remove("keyboard-open");
      document.documentElement.style.removeProperty("--viewport-height");
    };
  }, []);
  return (
    <>
      <PanelHeading
        active={view === "chat-view"}
        className="conversation-heading"
        id="conversation-toolbar"
      >
        <div className="conversation-title" id="mobile-conversation-heading">
          <span className="eyebrow">Conversation</span>
          <h2 id="session-title" title={chat.title}>
            <span id="mobile-session-title">{chat.title}</span>
          </h2>
          <span id="conversation-cost" className="cost-label">
            <span id="mobile-conversation-cost">
              {chat.id ? "Conversation cost: " + formatCost(chat.usage) : ""}
            </span>
          </span>
        </div>
        {!mobile && <ConversationActions />}
      </PanelHeading>
      <section
        id="chat-view"
        className="chat-view"
        hidden={view !== "chat-view"}
        ref={chatView}
      >
        <div id="notifications" aria-live="polite">
          {notifications.map((notification, index) => (
            <p key={index}>Reminder: {notification.text}</p>
          ))}
        </div>
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
          <small className="footnote">
            Review external actions before you approve them.
          </small>
        </div>
      </section>
    </>
  );
}
