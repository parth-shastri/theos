"use client";

import { createParser, Renderer } from "@openuidev/react-lang";
import {
  Component,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import {
  OPENUI_COMPATIBLE_VERSIONS,
  OpenUIAnswerContext,
  openuiLibrary,
} from "../openui/library";
import { SelectPicker } from "./Primitives";
import OpenUIDatePicker from "./OpenUIDatePicker";

const ISSUE_CODES = new Set([
  "unknown-component",
  "missing-required",
  "null-required",
  "type-mismatch",
  "excess-args",
  "inline-reserved",
  "unknown-function",
  "no-root",
  "tool-not-found",
  "tool-error",
  "mcp-error",
  "parse-failed",
  "parse-exception",
  "runtime-error",
  "render-error",
  "library-version-mismatch",
  "incomplete",
  "unresolved",
  "orphaned",
  "missing-summary",
]);

const STATE_FIELDS = new Set([
  "reminder_text",
  "reminder_date",
  "reminder_time",
  "reminder_timezone",
  "reminder_recurrence",
  "reminder_weekdays",
]);

function componentCount(root) {
  let count = 0;
  const visit = (value, depth) => {
    if (depth > 20 || count >= 100 || !value || typeof value !== "object")
      return;
    if (Array.isArray(value)) {
      value.slice(0, 100).forEach((item) => visit(item, depth + 1));
      return;
    }
    if (value.type === "element") count++;
    Object.values(value).forEach((item) => visit(item, depth + 1));
  };
  visit(root, 0);
  return count;
}

function parseSummary(result) {
  const errors = (result?.meta?.errors || [])
    .filter((error) => error.severity !== "warning")
    .map((error) => error.code)
    .filter((code) => typeof code === "string")
    .slice(0, 16);
  const unresolved = result?.meta?.unresolved || [];
  const orphaned = result?.meta?.orphaned || [];
  const root = result?.root;
  const node = root?.props?.summary;
  const text = node?.props?.text;
  const summary =
    root?.typeName === "TheosAnswer" &&
    node?.typeName === "AnswerSummary" &&
    !node.partial &&
    !node.hasDynamicProps &&
    typeof text === "string"
      ? text.trim().slice(0, 4000)
      : "";
  return {
    root: root?.typeName || null,
    summary,
    incomplete: Boolean(result?.meta?.incomplete),
    errors,
    unresolvedCount: Math.min(unresolved.length, 100),
    orphanedCount: Math.min(orphaned.length, 100),
    componentCount: componentCount(result?.root),
  };
}

function filterState(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => STATE_FIELDS.has(key))
      .map(([key, field]) => [
        key,
        field &&
        typeof field === "object" &&
        !Array.isArray(field) &&
        "value" in field
          ? field.value
          : field,
      ]),
  );
}

function actionText(event) {
  if (event.formName === "schedule_reminder") {
    const values = event.formState || {};
    const text =
      typeof values.reminder_text === "string"
        ? values.reminder_text.trim()
        : "";
    const days = Array.isArray(values.reminder_weekdays)
      ? values.reminder_weekdays.join(", ")
      : "";
    const repeat =
      {
        none: "once",
        daily: "every day",
        weekly: "every week",
        weekdays: "on weekdays",
        custom: days ? `on ${days}` : "on selected days",
      }[values.reminder_recurrence] || "once";
    const details = [
      values.reminder_date,
      values.reminder_time,
      values.reminder_timezone,
    ]
      .filter((value) => typeof value === "string" && value)
      .join(" ");
    const title = text
      ? `Schedule reminder: ${text.slice(0, 280)}`
      : "Schedule a reminder";
    return `${title}${details ? ` — ${details}` : ""}; ${repeat}`.slice(0, 500);
  }
  return (event.humanFriendlyMessage || "Continue this conversation").slice(
    0,
    500,
  );
}

export default function OpenUIAnswer({ entry, sessionId, renderSpeech }) {
  const {
    chat,
    me,
    openUIAction,
    saveOpenUIState,
    reportOpenUIIssue,
    showError,
  } = useWorkspace();
  const [rendererErrors, setRendererErrors] = useState([]);
  const [summary, setSummary] = useState(entry.openuiSummary || "");
  const [draftState, setDraftState] = useState(entry.openuiState || {});
  const [actionPending, setActionPending] = useState(false);
  const reported = useRef(false);
  const timer = useRef(null);
  const previousState = useRef(JSON.stringify(entry.openuiState || {}));
  const streaming = Boolean(entry.streaming);
  const versionMatches = OPENUI_COMPATIBLE_VERSIONS.has(entry.libraryVersion);
  const parseStatus = useMemo(() => {
    if (streaming) return null;
    try {
      return parseSummary(
        createParser(openuiLibrary.toJSONSchema(), openuiLibrary.root).parse(
          entry.text,
        ),
      );
    } catch {
      return {
        root: null,
        summary: "",
        incomplete: true,
        errors: ["parse-exception"],
        unresolvedCount: 0,
        orphanedCount: 0,
        componentCount: 0,
      };
    }
  }, [streaming, entry.text]);
  const accepted =
    !streaming &&
    versionMatches &&
    Boolean(entry.openuiMessageId && parseStatus.summary) &&
    !parseStatus.incomplete &&
    parseStatus.errors.length === 0 &&
    rendererErrors.length === 0 &&
    parseStatus.unresolvedCount === 0 &&
    parseStatus.orphanedCount === 0;
  const fallbackSummary = parseStatus?.summary || entry.openuiSummary || "";
  const busy = chat.busy || chat.approvals.length > 0 || actionPending;

  // Reset before child effects publish the rendered summary and form defaults.
  useLayoutEffect(() => {
    setSummary(entry.openuiSummary || "");
    setDraftState(entry.openuiState || {});
    previousState.current = JSON.stringify(entry.openuiState || {});
    reported.current = false;
    setRendererErrors([]);
  }, [entry.openuiMessageId]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onRendererError = useCallback(
    (errors) => {
      if (streaming) return;
      const codes = (errors || [])
        .filter((error) => error.severity !== "warning")
        .map((error) => error.code)
        .filter((code) => typeof code === "string")
        .slice(0, 16);
      setRendererErrors([...new Set(codes)]);
    },
    [streaming],
  );
  const onStateUpdate = useCallback((state) => {
    const next = filterState(state);
    const encoded = JSON.stringify(next);
    if (encoded !== previousState.current) {
      previousState.current = encoded;
      setDraftState(next);
    }
  }, []);
  const onSummary = useCallback((value) => {
    if (typeof value === "string") setSummary(value.slice(0, 4000));
  }, []);

  useEffect(() => {
    if (
      streaming ||
      entry.presentationHidden ||
      !entry.openuiMessageId ||
      !sessionId
    )
      return;
    const text = accepted ? summary || fallbackSummary : fallbackSummary;
    if (!accepted && (!text || text === entry.openuiSummary)) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      saveOpenUIState(
        sessionId,
        entry.openuiMessageId,
        accepted ? draftState : entry.openuiState || {},
        text,
      ).catch(() => {});
    }, 400);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [
    streaming,
    accepted,
    entry.openuiMessageId,
    entry.openuiState,
    entry.openuiSummary,
    entry.presentationHidden,
    sessionId,
    fallbackSummary,
    draftState,
    summary,
    saveOpenUIState,
  ]);

  useEffect(() => {
    if (
      streaming ||
      reported.current ||
      accepted ||
      entry.presentationHidden ||
      !entry.openuiMessageId
    )
      return;
    reported.current = true;
    const codes = [
      ...new Set([
        ...parseStatus.errors,
        ...rendererErrors,
        ...(!versionMatches ? ["library-version-mismatch"] : []),
        ...(parseStatus.incomplete ? ["incomplete"] : []),
        ...(parseStatus.unresolvedCount ? ["unresolved"] : []),
        ...(parseStatus.orphanedCount ? ["orphaned"] : []),
        ...(parseStatus.root === "TheosAnswer" && !parseStatus.summary
          ? ["missing-summary"]
          : []),
      ]),
    ];
    reportOpenUIIssue({
      library_version: entry.libraryVersion || "unknown",
      codes: codes.length
        ? [
            ...new Set(
              codes.map((code) => (ISSUE_CODES.has(code) ? code : "other")),
            ),
          ].slice(0, 16)
        : ["parse-failed"],
      component_count: parseStatus.componentCount,
      unresolved_count: parseStatus.unresolvedCount,
      orphaned_count: parseStatus.orphanedCount,
    }).catch(() => {});
  }, [
    streaming,
    accepted,
    entry.openuiMessageId,
    entry.libraryVersion,
    entry.presentationHidden,
    versionMatches,
    parseStatus,
    rendererErrors,
    reportOpenUIIssue,
  ]);

  const action = async (event) => {
    if (!accepted || busy || event.type !== "continue_conversation") return;
    setActionPending(true);
    const formValues = filterState(event.formState ?? draftState);
    try {
      await saveOpenUIState(
        sessionId,
        entry.openuiMessageId,
        formValues,
        summary,
      );
      await openUIAction(sessionId, {
        type: "continue_conversation",
        message_id: entry.openuiMessageId,
        label: (
          event.humanFriendlyMessage || "Continue this conversation"
        ).slice(0, 240),
        form_name: event.formName || null,
        values: formValues,
        context: event.params?.context ?? null,
        visible_text: actionText({ ...event, formState: formValues }),
      });
    } catch (error) {
      showError(error);
    } finally {
      setActionPending(false);
    }
  };
  const explainInText = async () => {
    if (busy || !entry.openuiMessageId) return;
    setActionPending(true);
    try {
      await openUIAction(sessionId, {
        type: "explain_in_text",
        message_id: entry.openuiMessageId,
        visible_text: "Explain this answer in text",
      });
    } catch (error) {
      showError(error);
    } finally {
      setActionPending(false);
    }
  };

  const context = useMemo(
    () => ({
      disabled: streaming || busy || !accepted,
      userTimezone: me?.timezone || "UTC",
      savedState: entry.openuiState || {},
      SelectPicker,
      DatePicker: OpenUIDatePicker,
      onSummary,
    }),
    [streaming, busy, accepted, me?.timezone, entry.openuiState, onSummary],
  );

  if (entry.presentationHidden) return null;
  if (!streaming && !accepted) {
    return (
      <div className="body openui-fallback">
        {fallbackSummary && (
          <p className="openui-answer-summary">{fallbackSummary}</p>
        )}
        <p>
          {fallbackSummary
            ? "The interactive details could not be displayed."
            : "This interactive answer could not be displayed."}
        </p>
        {entry.openuiMessageId && (
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={explainInText}
          >
            Explain in text
          </button>
        )}
        {fallbackSummary && renderSpeech?.(fallbackSummary)}
      </div>
    );
  }

  return (
    <div className="body openui-answer-body">
      {versionMatches && (
        <OpenUIAnswerContext.Provider value={context}>
          <OpenUIRenderBoundary
            key={entry.openuiMessageId}
            onFailure={() => setRendererErrors(["render-error"])}
          >
            <Renderer
              response={entry.text}
              library={openuiLibrary}
              isStreaming={streaming}
              initialState={entry.openuiState || {}}
              onAction={action}
              onStateUpdate={onStateUpdate}
              onError={onRendererError}
            />
          </OpenUIRenderBoundary>
        </OpenUIAnswerContext.Provider>
      )}
      {streaming && (
        <div className="openui-pending" aria-live="polite">
          Preparing an interactive answer…
        </div>
      )}
      {!streaming && summary && renderSpeech?.(summary)}
    </div>
  );
}

class OpenUIRenderBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onFailure();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
