import {
  Fragment,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { formatCost } from "../state/chat";
import { commands, generationFields } from "../state/config";
import { Dialog, Icon, SelectPicker } from "./Primitives";
import Markdown from "./Markdown";

function SettingsDialog() {
  const { me, chat, dialog, closeDialog, mobile, patchSettings, status } =
    useWorkspace();
  const open = dialog?.kind === "settings";
  const [model, setModel] = useState(""),
    [reasoning, setReasoning] = useState("default"),
    [generation, setGeneration] = useState({});
  const [autoSpeech, setAutoSpeech] = useState(false),
    [saving, setSaving] = useState(false),
    [error, setError] = useState(""),
    [expanded, setExpanded] = useState(false);
  const capabilities = me?.generation_capabilities[model] || {
    parameters: [],
    reasoning: ["default"],
  };
  const models = useMemo(
    () => (me?.models || []).map((value) => ({ value, label: value })),
    [me],
  );
  const choices = useMemo(
    () =>
      (capabilities.reasoning || ["default"]).map((value) => ({
        value,
        label: value === "default" ? "Default" : value,
      })),
    [capabilities.reasoning],
  );
  useLayoutEffect(() => {
    if (!open) return;
    setModel(chat.model);
    setReasoning(chat.reasoning);
    setGeneration(chat.generation || {});
    setAutoSpeech(
      me?.voice.tts && sessionStorage.getItem("theos-tts-" + me.id) === "true",
    );
    setExpanded(false);
    setError("");
    const frame = requestAnimationFrame(() => {
      const id =
        dialog.section === "voice"
          ? "auto-speech"
          : ["model", "reasoning"].includes(dialog.section)
            ? document.getElementById(dialog.section + "-trigger")
              ? dialog.section + "-trigger"
              : dialog.section
            : null;
      if (id) document.getElementById(id)?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [open, dialog?.request]);
  const close = () => {
    if (!saving) {
      closeDialog();
      if (mobile) document.getElementById("toggle-sidebar")?.focus();
    }
  };
  const changeModel = (value) => {
    setModel(value);
    const next = me.generation_capabilities[value];
    if (!next.reasoning.includes(reasoning)) setReasoning("default");
    if (generation.max_output_tokens != null)
      setGeneration((previous) => ({
        ...previous,
        max_output_tokens: Math.min(
          previous.max_output_tokens,
          next.max_output_tokens,
        ),
      }));
  };
  return (
    <Dialog
      id="generation-dialog"
      aria-labelledby="generation-title"
      open={open}
      onClose={close}
      saving={saving}
    >
      <form
        id="generation-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (saving) return;
          setSaving(true);
          setError("");
          try {
            const values = Object.fromEntries(
              capabilities.parameters
                .filter(
                  (key) => generation[key] !== "" && generation[key] != null,
                )
                .map((key) => [key, Number(generation[key])]),
            );
            await patchSettings({ model, reasoning, generation: values });
            sessionStorage.setItem("theos-tts-" + me.id, String(autoSpeech));
            closeDialog();
            if (mobile) document.getElementById("toggle-sidebar")?.focus();
          } catch (error) {
            if (error.name !== "AbortError") setError(error.message);
          } finally {
            setSaving(false);
          }
        }}
        onInvalid={(event) => {
          if (event.target.closest("#generation-fields")) setExpanded(true);
        }}
      >
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">Conversation</span>
            <h2 id="generation-title">Settings</h2>
          </div>
          <button
            id="generation-close"
            className="icon-button"
            type="button"
            aria-label="Close settings"
            title="Close settings"
            disabled={saving}
            onClick={close}
          >
            <Icon name="cancel" />
          </button>
        </div>
        <p id="settings-conversation">{chat.title}</p>
        <div className="settings-model-fields">
          <div className="generation-field">
            <SelectPicker
              id="model"
              label="Model"
              value={model}
              options={models}
              onChange={changeModel}
              icon="memory"
              disabled={saving || !open}
              describedBy="model-hint"
            />
            <small id="model-hint">Choose a model for this conversation.</small>
          </div>
          <div className="generation-field">
            <SelectPicker
              id="reasoning"
              label="Reasoning effort"
              value={reasoning}
              options={choices}
              onChange={setReasoning}
              icon="settings"
              disabled={saving || !open}
              describedBy="reasoning-hint"
            />
            <small id="reasoning-hint">
              Options depend on the selected model.
            </small>
          </div>
        </div>
        <details
          id="generation-options"
          className="settings-section"
          open={expanded}
          onToggle={(event) => {
            if (event.target === event.currentTarget)
              setExpanded(event.currentTarget.open);
          }}
        >
          <summary>Generation parameters</summary>
          <p id="generation-model">Model: {model}</p>
          <p>Leave a value empty to use the model's default.</p>
          <div id="generation-fields" className="generation-fields">
            {capabilities.parameters.map((key) => {
              const spec = generationFields[key],
                id = "generation-" + key;
              return (
                <div className="generation-field" key={key}>
                  <label htmlFor={id}>{spec.label}</label>
                  <input
                    id={id}
                    name={key}
                    type="number"
                    min={spec.min}
                    max={
                      key === "max_output_tokens"
                        ? capabilities.max_output_tokens
                        : spec.max
                    }
                    step={spec.step}
                    placeholder={
                      key === "max_output_tokens"
                        ? String(
                            Math.min(
                              me?.default_max_output_tokens || 8192,
                              capabilities.max_output_tokens,
                            ),
                          )
                        : "Model default"
                    }
                    value={generation[key] ?? ""}
                    disabled={saving}
                    aria-describedby={id + "-hint"}
                    onChange={(event) =>
                      setGeneration({
                        ...generation,
                        [key]: event.target.value,
                      })
                    }
                  />
                  <small id={id + "-hint"}>{spec.description}</small>
                </div>
              );
            })}
            {!capabilities.parameters.length && (
              <p>This model uses its default generation parameters.</p>
            )}
          </div>
          <button
            id="generation-defaults"
            type="button"
            disabled={saving}
            onClick={() => setGeneration({})}
          >
            Use parameter defaults
          </button>
        </details>
        <fieldset className="voice-settings">
          <legend>Voice</legend>
          <p id="voice-services">
            {"Microphone transcription: " +
              (me?.voice.transcription ? "configured" : "unavailable") +
              ". TTS playback: " +
              (me?.voice.tts ? "configured" : "unavailable") +
              "."}
          </p>
          <label>
            <input
              id="auto-speech"
              type="checkbox"
              disabled={saving || !me?.voice.tts}
              checked={!!autoSpeech}
              onChange={(event) => setAutoSpeech(event.target.checked)}
            />{" "}
            Read new replies aloud
          </label>
          <small>
            Microphone recordings become editable text. Use the speaker button
            for speech playback.
          </small>
        </fieldset>
        <p id="generation-error" className="error" role="alert">
          {error}
        </p>
        <div className="dialog-actions">
          <button
            id="generation-cancel"
            type="button"
            disabled={saving}
            onClick={close}
          >
            Cancel
          </button>
          <button className="primary" type="submit" disabled={saving}>
            Save settings
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function UsageDialog() {
  const { chat, dialog, closeDialog, json, syncUsage } = useWorkspace();
  const open = dialog?.kind === "usage";
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open || !chat.id) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    setLoading(true);
    Promise.all([
      json("/api/sessions/" + chat.id, { signal: controller.signal }),
      json("/api/usage", { signal: controller.signal }),
    ])
      .then(([session, usage]) => {
        if (!controller.signal.aborted) {
          setData({ session, usage });
          syncUsage(session, usage);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [open, chat.id, refresh, json, syncUsage]);
  return (
    <Dialog
      id="usage-dialog"
      aria-labelledby="usage-title"
      open={open}
      onClose={closeDialog}
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">Your workspace</span>
          <h2 id="usage-title">Usage</h2>
        </div>
        <button
          id="usage-close"
          className="icon-button"
          type="button"
          aria-label="Close usage"
          title="Close usage"
          onClick={closeDialog}
        >
          <Icon name="cancel" />
        </button>
      </div>
      <p id="usage-status" role="status" className={error ? "error" : ""}>
        {error ||
          (loading ? "Loading usage…" : data ? "Recorded usage · USD" : "")}
      </p>
      <div id="usage-content" className="usage-grid">
        {data &&
          [
            ["This conversation", data.session.usage, data.session.title],
            ["Your total", data.usage, "All your conversations and transports"],
          ].map(([title, summary, subtitle]) => (
            <section className="usage-card" key={title}>
              <h3>{title}</h3>
              <p className="usage-subtitle">{subtitle}</p>
              <strong className="usage-cost">{formatCost(summary)}</strong>
              <dl className="usage-metrics">
                {[
                  ["Requests", summary.requests],
                  ["Input tokens", summary.input_tokens],
                  ["Output tokens", summary.output_tokens],
                  ["Unpriced requests", summary.unpriced_requests],
                ].map(([label, value]) => (
                  <Fragment key={label}>
                    <dt>{label}</dt>
                    <dd>{new Intl.NumberFormat().format(value)}</dd>
                  </Fragment>
                ))}
              </dl>
              {!!summary.unpriced_requests && (
                <p className="usage-warning">
                  Some requests have no recorded price. The cost is incomplete.
                </p>
              )}
            </section>
          ))}
      </div>
      <p className="usage-note">
        Costs use reported amounts or configured USD estimates. Requests without
        a recorded price remain visible.
      </p>
      <div className="dialog-actions">
        <button
          id="usage-refresh"
          type="button"
          disabled={loading}
          onClick={() => setRefresh((value) => value + 1)}
        >
          Refresh usage
        </button>
      </div>
    </Dialog>
  );
}
function ResearchDialog() {
  const { chat, dialog, closeDialog, json, mobile } = useWorkspace();
  const open = dialog?.kind === "research";
  const [runs, setRuns] = useState([]),
    [detail, setDetail] = useState(null),
    [status, setStatus] = useState(""),
    [refresh, setRefresh] = useState(0);
  const request = useRef(0);
  useEffect(() => {
    if (!open || !chat.id) return;
    const controller = new AbortController(),
      id = ++request.current;
    setDetail(null);
    setStatus("Loading saved research…");
    json("/api/sessions/" + chat.id + "/research", {
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted || request.current !== id) return;
        setRuns(result);
        setStatus(
          result.length
            ? "Select a researcher to inspect findings and sources."
            : "No saved deep research in this conversation.",
        );
      })
      .catch((error) => {
        if (!controller.signal.aborted) setStatus(error.message);
      });
    return () => {
      controller.abort();
      request.current++;
    };
  }, [open, chat.id, refresh, json]);
  const close = () => {
    request.current++;
    closeDialog();
    if (mobile) document.getElementById("toggle-sidebar")?.focus();
  };
  return (
    <Dialog
      id="research-dialog"
      aria-labelledby="research-title"
      open={open}
      onClose={close}
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">Saved evidence</span>
          <h2 id="research-title">Research</h2>
        </div>
        <button
          id="research-close"
          type="button"
          aria-label="Close research"
          onClick={close}
        >
          Close
        </button>
      </div>
      <p id="research-status" role="status">
        {status}
      </p>
      <div id="research-runs" className="research-runs">
        {runs.map((run) => (
          <button
            key={run.id}
            onClick={async () => {
              const id = ++request.current;
              try {
                const result = await json(
                  "/api/sessions/" + chat.id + "/research/" + run.id,
                );
                if (id === request.current) {
                  setDetail(result);
                  setRuns((runs) =>
                    runs.map((value) => (value.id === run.id ? result : value)),
                  );
                }
              } catch (error) {
                if (id === request.current) setStatus(error.message);
              }
            }}
          >
            {run.name + " · " + run.status}
          </button>
        ))}
      </div>
      <div id="research-detail" className="research-detail">
        {detail && (
          <>
            <h3>{detail.name}</h3>
            <p>{detail.task}</p>
            <p>{detail.reason || detail.status}</p>
            {detail.answer && (
              <>
                <h3>Report</h3>
                <Markdown className="markdown-body" source={detail.answer} />
              </>
            )}
            {!!detail.scratchpad.length && <h3>Evidence scratchpad</h3>}
            {detail.scratchpad.map((item) => (
              <details key={item.id}>
                <summary>
                  {item.kind +
                    ": " +
                    (item.content.title || item.content.url || item.id)}
                </summary>
                <SourceLink url={item.content.url} />
                <pre>{JSON.stringify(item.content, null, 2)}</pre>
              </details>
            ))}
            <details>
              <summary>Original research transcript</summary>
              <pre>{JSON.stringify(detail.history, null, 2)}</pre>
            </details>
            <details>
              <summary>Saved summary checkpoints</summary>
              <pre>{JSON.stringify(detail.checkpoints, null, 2)}</pre>
            </details>
          </>
        )}
      </div>
      <div className="dialog-actions">
        <button
          id="research-refresh"
          type="button"
          onClick={() => setRefresh((value) => value + 1)}
        >
          Refresh
        </button>
      </div>
    </Dialog>
  );
}
function SourceLink({ url }) {
  try {
    const parsed = new URL(url);
    if (["https:", "http:"].includes(parsed.protocol))
      return (
        <a href={parsed.href} target="_blank" rel="noopener noreferrer">
          {url}
        </a>
      );
  } catch {}
  return null;
}
function HelpDialog() {
  const { dialog, closeDialog, runCommand, editDraft, perform } =
    useWorkspace();
  return (
    <Dialog
      id="help-dialog"
      aria-labelledby="help-title"
      open={dialog?.kind === "help"}
      onClose={closeDialog}
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">Shortcuts</span>
          <h2 id="help-title">Commands</h2>
        </div>
        <button
          id="help-close"
          className="icon-button"
          type="button"
          aria-label="Close command help"
          title="Close command help"
          onClick={closeDialog}
        >
          <Icon name="cancel" />
        </button>
      </div>
      <p>Choose a command. Commands with options show a selection menu.</p>
      <div id="help-commands" className="help-commands">
        {commands.map((command) => (
          <button
            type="button"
            className="help-command"
            key={command.name}
            onClick={() => {
              closeDialog();
              if (command.argument) editDraft("/" + command.name + " ", true);
              else perform(() => runCommand("/" + command.name));
            }}
          >
            <strong>/{command.name}</strong>
            <span>{command.description}</span>
            {command.argument && <small>Choose an option →</small>}
          </button>
        ))}
      </div>
      <p className="keyboard-hint">
        Type / for commands or @ for connections. ↑ ↓ to select · Enter or Tab
        to choose · Escape to close.
        <br />
        Enter to send · Shift + Enter for a new line.
      </p>
    </Dialog>
  );
}
export default function Dialogs() {
  return (
    <>
      <SettingsDialog />
      <ResearchDialog />
      <UsageDialog />
      <HelpDialog />
    </>
  );
}
