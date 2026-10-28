"use client";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { commands, messageModes } from "../state/config";
import { useRecorder } from "../hooks/useRecorder";
import {
  appendTranscript,
  useComposerPrompt,
} from "../hooks/useComposerPrompt";
import { ConnectionIcon, Glass, Icon } from "./Primitives";

export default function Composer() {
  const {
    me,
    chat,
    mobile,
    busy,
    working,
    json,
    showError,
    status,
    send,
    runCommand,
    openDialog,
    draftRequest,
    connections,
    refreshConnections,
  } = useWorkspace();
  const [draft, setDraft] = useState(""),
    [files, setFiles] = useState([]);
  const [mode, setMode] = useState("normal"),
    [menu, setMenu] = useState("");
  const [focused, setFocused] = useState(false);
  const [caret, setCaret] = useState({ start: 0, end: 0 }),
    [dismissed, setDismissed] = useState(false);
  const [composing, setComposing] = useState(false),
    [commandIndex, setCommandIndex] = useState(0);
  const message = useRef(null),
    form = useRef(null),
    upload = useRef(null),
    modeTrigger = useRef(null),
    add = useRef(null);
  const freshConnections = useRef(0),
    fetchingConnections = useRef(false),
    pendingCaret = useRef(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const voice = useRecorder((text) => {
    const next = appendTranscript(draftRef.current, text);
    setDraft(next);
    message.current.focus();
  });
  const placeholder = useComposerPrompt({
    active: !!me,
    draft,
    focused,
    mobile,
    activity: voice.activity,
  });
  const mention = useMemo(() => {
    if (caret.start !== caret.end) return null;
    const match = draft.slice(0, caret.start).match(/(?:^|\s)@([a-z0-9_-]*)$/i);
    return match
      ? {
          query: match[1].toLowerCase(),
          start: caret.start - match[1].length - 1,
          end:
            caret.start +
            (draft.slice(caret.start).match(/^[a-z0-9_-]*/i)?.[0].length || 0),
        }
      : null;
  }, [draft, caret]);
  useEffect(() => {
    if (
      !mention ||
      dismissed ||
      busy ||
      fetchingConnections.current ||
      Date.now() - freshConnections.current < 15000
    )
      return;
    fetchingConnections.current = true;
    refreshConnections()
      .then(() => {
        freshConnections.current = Date.now();
      })
      .catch(() => {})
      .finally(() => {
        fetchingConnections.current = false;
      });
  }, [mention, dismissed, busy, refreshConnections]);
  const matches = useMemo(() => {
    if (!me || busy || dismissed || composing || !focused) return [];
    if (mention) {
      const catalog = [
        ...(connections?.accounts || []).map((account) => ({
          ...account,
          status: !account.configured
            ? "Not configured"
            : account.connected
              ? "Connected"
              : "Sign-in required",
        })),
        ...(connections?.services || [])
          .filter((service) => service.configured)
          .map((service) => ({ ...service, status: "Configured" })),
      ];
      return catalog
        .filter(
          (connection) =>
            connection.id.startsWith(mention.query) ||
            connection.name.toLowerCase().startsWith(mention.query),
        )
        .map((connection) => ({
          value: "@" + connection.id,
          description: connection.status,
          connection,
        }));
    }
    if (!/^\/[^\n]*$/.test(draft)) return [];
    let [name, ...args] = draft.slice(1).toLowerCase().split(/\s+/);
    if (name === "thinking") name = "reasoning";
    if (args.length) {
      const values =
        name === "model"
          ? me.models
          : name === "reasoning"
            ? me.generation_capabilities[chat.model]?.reasoning || ["default"]
            : [];
      return values
        .filter((value) => value.toLowerCase().startsWith(args.join(" ")))
        .map((value) => ({
          value: "/" + name + " " + value,
          description:
            value === chat[name === "model" ? "model" : "reasoning"]
              ? "Current selection"
              : name === "model"
                ? "Choose model"
                : "Set reasoning effort",
        }));
    }
    return commands
      .filter((command) => command.name.startsWith(name))
      .map((command) => ({ ...command, value: "/" + command.name }));
  }, [
    me,
    busy,
    dismissed,
    composing,
    focused,
    mention,
    connections,
    draft,
    chat.model,
    chat.reasoning,
  ]);
  const choose = (index) => {
    const command = matches[index];
    if (!command) return;
    let next;
    if (command.connection && mention) {
      const after = draft.slice(mention.end),
        separated = /^\s/.test(after),
        separator = separated ? after[0] : " ";
      next =
        draft.slice(0, mention.start) +
        command.value +
        separator +
        after.slice(separated ? 1 : 0);
      pendingCaret.current = mention.start + command.value.length + 1;
    } else next = command.value + (command.argument ? " " : "");
    setDraft(next);
    setDismissed(!command.argument);
    setCommandIndex(0);
    message.current.focus();
  };
  useLayoutEffect(() => {
    const element = message.current;
    element.style.height = "auto";
    if (draft)
      element.style.height =
        Math.max(44, Math.min(element.scrollHeight, 140)) + "px";
    if (pendingCaret.current !== null) {
      element.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  }, [draft]);
  useEffect(() => {
    if (!draftRequest) return;
    setDraft(draftRequest.text);
    setDismissed(!draftRequest.suggest);
    setCommandIndex(0);
    setCaret({
      start: draftRequest.text.length,
      end: draftRequest.text.length,
    });
    message.current.focus();
  }, [draftRequest]);
  useEffect(() => {
    setMode("normal");
  }, [chat.id, chat.revision]);
  useEffect(() => {
    setDraft("");
    setFiles([]);
    setMenu("");
    setDismissed(true);
  }, [me?.id]);
  useEffect(() => {
    if (busy) {
      setMenu("");
      setDismissed(true);
    }
  }, [busy]);
  useLayoutEffect(() => {
    if (matches.length)
      document
        .getElementById("command-option-" + commandIndex)
        ?.scrollIntoView({ block: "nearest" });
  }, [matches, commandIndex]);
  useLayoutEffect(() => {
    if (menu === "options")
      form.current
        .querySelector("#composer-options button:not(:disabled)")
        ?.focus();
    if (menu === "mode")
      form.current.querySelector('#mode-menu [aria-selected="true"]')?.focus();
  }, [menu]);
  useEffect(() => {
    const click = (event) => {
      if (
        !event.target.closest(
          "#composer-options,#composer-add,#mode-menu,#mode-trigger",
        )
      )
        setMenu("");
    };
    const key = (event) => {
      if (event.key === "Escape" && menu) {
        setMenu("");
        (menu === "mode" ? modeTrigger : add).current?.focus();
      }
    };
    document.addEventListener("click", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("click", click);
      document.removeEventListener("keydown", key);
    };
  }, [menu]);
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    const text = draft.trim();
    if (!text && !files.length) return;
    if (text.startsWith("/")) {
      if (files.length)
        return showError(
          new Error(
            "Send attached files with a message before using a command.",
          ),
        );
      setDraft("");
      setDismissed(true);
      try {
        await runCommand(text);
      } catch (error) {
        setDraft(text);
        showError(error);
      }
      return;
    }
    const attached = files.map((file) => file.id),
      selectedMode = mode;
    setDraft("");
    setFiles([]);
    setMode("normal");
    try {
      await send(text, attached, selectedMode);
    } catch (error) {
      showError(error);
    }
  };
  const keydown = (event) => {
    if (mobile && event.key === "Enter") return;
    if (matches.length && !event.nativeEvent.isComposing) {
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        setCommandIndex(
          (index) =>
            (index + (event.key === "ArrowDown" ? 1 : -1) + matches.length) %
            matches.length,
        );
        return;
      }
      if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
        event.preventDefault();
        choose(commandIndex);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissed(true);
        return;
      }
    }
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      form.current.requestSubmit();
    }
  };
  const modeKey = (event) => {
    const options = [
        ...form.current.querySelectorAll("#mode-menu [data-mode]"),
      ],
      index = options.indexOf(document.activeElement);
    if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      options[
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? options.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) %
              options.length
      ]?.focus();
    } else if (["Escape", "Tab"].includes(event.key)) {
      if (event.key === "Escape") event.preventDefault();
      setMenu("");
      modeTrigger.current.focus();
    }
  };
  const recordLabel = voice.recording
    ? "Stop voice recording"
    : "Record a voice message";
  const recordTitle = voice.recording
    ? recordLabel
    : voice.canRecord
      ? "Record, transcribe, and review a voice message"
      : !me?.voice.transcription
        ? "Transcription service is not configured"
        : "Microphone recording requires HTTPS or localhost and a supported browser";
  const statusText = voice.activity || chat.status;
  const statusClass = voice.activity
    ? "voice-status" + (!draft ? " placeholder-status" : "")
    : chat.statusClass;
  const currentMode = messageModes[mode];
  const trackCaret = () =>
    setCaret({
      start: message.current.selectionStart,
      end: message.current.selectionEnd,
    });
  return (
    <Glass
      as="form"
      id="composer"
      ref={form}
      className={
        (draft || files.length || mode !== "normal" ? "has-draft" : "") +
        (voice.recording ? " is-recording" : "")
      }
      onSubmit={submit}
      onBlur={() => {
        requestAnimationFrame(() => {
          if (!form.current?.contains(document.activeElement)) setMenu("");
        });
      }}
    >
      <div
        id="command-suggestions"
        className="command-suggestions"
        role="listbox"
        aria-label={mention ? "Connections" : "Slash commands"}
        hidden={!matches.length}
      >
        {matches.map((match, index) => (
          <button
            type="button"
            className={
              "command-option" + (match.connection ? " connection-option" : "")
            }
            id={"command-option-" + index}
            role="option"
            aria-selected={index === commandIndex}
            key={match.value}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => choose(index)}
          >
            {match.connection ? (
              <div className="mention-identity">
                <ConnectionIcon id={match.connection.id} />
                <strong>{match.value}</strong>
              </div>
            ) : (
              <strong>
                {match.value + (match.argument ? " " + match.argument : "")}
              </strong>
            )}
            <span>{match.description}</span>
          </button>
        ))}
      </div>
      <label className="sr-only" htmlFor="message">
        Message
      </label>
      <Glass
        id="composer-options"
        className="composer-options"
        role="group"
        aria-label="Add files and options"
        hidden={menu !== "options"}
        onClick={(event) => {
          if (event.target.closest("button")) setMenu("");
        }}
      >
        <button
          id="attach-files"
          className="composer-option"
          type="button"
          disabled={busy}
          aria-label="Attach files"
          title="Attach files"
          onClick={() => upload.current.click()}
        >
          <Icon name="attach" />
          <span>Attach files</span>
        </button>
        <input
          id="upload"
          type="file"
          multiple
          hidden
          ref={upload}
          disabled={busy}
          onChange={async (event) => {
            const selected = [...event.target.files];
            event.target.value = "";
            try {
              for (const file of selected) {
                const form = new FormData();
                form.append("file", file);
                const result = await json("/api/files", {
                  method: "POST",
                  body: form,
                });
                setFiles((files) => [...files, result]);
              }
              message.current.focus();
            } catch (error) {
              showError(error);
            }
          }}
        />
        <button
          id="command-help"
          className="composer-option"
          type="button"
          disabled={busy}
          aria-label="Show command and connection help"
          title="Show command and connection help"
          onClick={() => openDialog("help")}
        >
          <Icon name="command" />
          <span>Commands & connections</span>
        </button>
        <button
          id="composer-settings"
          className="composer-option"
          type="button"
          disabled={busy}
          onClick={() => openDialog("settings")}
        >
          <Icon name="settings" />
          Conversation settings
        </button>
      </Glass>
      <Glass
        id="mode-menu"
        className="mode-menu"
        role="listbox"
        aria-label="Message mode"
        hidden={menu !== "mode"}
        onKeyDown={modeKey}
      >
        {Object.entries(messageModes).map(([value, option]) => (
          <button
            type="button"
            role="option"
            data-mode={value}
            aria-selected={mode === value}
            tabIndex={-1}
            key={value}
            onClick={() => {
              setMode(value);
              setMenu("");
              modeTrigger.current.focus();
            }}
          >
            <Icon name={option.icon} />
            <span className="mode-copy">
              <strong>{option.label}</strong>
              <small>{option.detail}</small>
            </span>
            <Icon name="check" className="mode-check" />
          </button>
        ))}
      </Glass>
      <div className="composer-row">
        <div className="composer-tools">
          <button
            id="composer-add"
            className="icon-button composer-action"
            type="button"
            aria-label="Add files and options"
            title="Add files and options"
            aria-expanded={menu === "options"}
            aria-controls="composer-options"
            disabled={busy}
            ref={add}
            onClick={() => {
              setDismissed(true);
              setMenu(menu === "options" ? "" : "options");
            }}
          >
            <Icon name="plus" />
          </button>
          <div className="research-controls composer-config">
            <input
              id="research-mode"
              type="hidden"
              value={mode}
              disabled={busy}
            />
            <button
              id="mode-trigger"
              type="button"
              aria-haspopup="listbox"
              aria-expanded={menu === "mode"}
              aria-controls="mode-menu"
              aria-describedby="research-mode-hint"
              data-mode={mode}
              aria-label={"Message mode: " + currentMode.label}
              disabled={busy}
              ref={modeTrigger}
              onClick={() => {
                setDismissed(true);
                setMenu(menu === "mode" ? "" : "mode");
              }}
              onKeyDown={(event) => {
                if (["ArrowUp", "ArrowDown"].includes(event.key)) {
                  event.preventDefault();
                  setMenu("mode");
                }
              }}
            >
              <Icon name={currentMode.icon} />
              <span>{currentMode.label}</span>
              <Icon name="chevron" />
            </button>
            <small id="research-mode-hint" className="sr-only">
              For this message only
            </small>
          </div>
        </div>
        <textarea
          id="message"
          role="combobox"
          aria-autocomplete="list"
          aria-controls="command-suggestions"
          aria-expanded={!!matches.length}
          aria-activedescendant={
            matches.length ? "command-option-" + commandIndex : undefined
          }
          aria-describedby="message-hint"
          aria-busy={voice.activity === "Transcribing..." ? true : undefined}
          placeholder={placeholder}
          enterKeyHint={mobile ? "enter" : "send"}
          rows={1}
          maxLength={32000}
          required={!files.length}
          ref={message}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setDismissed(false);
            setCommandIndex(0);
            setMenu("");
            trackCaret();
          }}
          onKeyDown={keydown}
          onFocus={() => setFocused(true)}
          onBlur={() => {
            setFocused(false);
            setDismissed(true);
          }}
          onSelect={trackCaret}
          onClick={() => {
            setDismissed(false);
            trackCaret();
          }}
          onCompositionStart={() => setComposing(true)}
          onCompositionEnd={() => {
            setComposing(false);
            setDismissed(false);
          }}
        />
        <div className="composer-actions">
          <button
            id="microphone"
            className={
              "icon-button voice-button" +
              (voice.recording ? " is-recording" : "")
            }
            type="button"
            aria-label={recordLabel}
            title={recordTitle}
            disabled={(busy && !voice.recording) || !voice.canRecord}
            onClick={voice.toggle}
          >
            <Icon name={voice.recording ? "stop" : "microphone"} />
          </button>
          <button
            id="cancel-recording"
            className="icon-button voice-button"
            type="button"
            aria-label="Cancel recording"
            title="Cancel recording"
            hidden={!voice.recording}
            onClick={voice.cancel}
          >
            <Icon name="cancel" />
          </button>
          <button
            className="primary icon-button send"
            id="send"
            type="submit"
            aria-label="Send message"
            title="Send message"
            disabled={busy}
          >
            <Icon name="send" />
          </button>
        </div>
      </div>
      <p id="status" role="status" aria-atomic="true" className={statusClass}>
        {statusText}
      </p>
      <div id="attachments">{files.map((file) => file.name).join(" · ")}</div>
      <span id="message-hint" className="sr-only">
        {mobile
          ? "Return for a new line · Use the send button to send"
          : "Enter to send · Shift + Enter for a new line"}
      </span>
    </Glass>
  );
}
