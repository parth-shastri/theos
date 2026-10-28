"use client";

import { createParser, Renderer } from "@openuidev/react-lang";
import {
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
  return {
    root: result?.root?.typeName || null,
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
  const [parsed, setParsed] = useState({
    root: null,
    errors: [],
    incomplete: false,
    unresolvedCount: 0,
    orphanedCount: 0,
    componentCount: 0,
  });
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
    if (streaming) return parsed;
    try {
      return parseSummary(
        createParser(openuiLibrary.toJSONSchema(), openuiLibrary.root).parse(
          entry.text,
        ),
      );
    } catch {
      return {
        root: null,
        incomplete: true,
        errors: ["parse-exception"],
        unresolvedCount: 0,
        orphanedCount: 0,
        componentCount: 0,
      };
    }
  }, [streaming, parsed, entry.text]);
  const accepted = useMemo(
    () =>
      !streaming &&
      versionMatches &&
      entry.openuiMessageId &&
      parseStatus.root === "TheosAnswer" &&
      !parseStatus.incomplete &&
      parseStatus.errors.length === 0 &&
      rendererErrors.length === 0 &&
      parseStatus.unresolvedCount === 0 &&
      parseStatus.orphanedCount === 0,
    [
      streaming,
      versionMatches,
      entry.openuiMessageId,
      parseStatus,
      rendererErrors.length,
    ],
  );
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

  const onParseResult = useCallback((result) => {
    const next = parseSummary(result);
    setParsed((current) =>
      JSON.stringify(current) === JSON.stringify(next) ? current : next,
    );
  }, []);
  const onRendererError = useCallback(
    (errors) => {
      if (streaming) return;
      const codes = (errors || [])
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
    if (streaming || !accepted || !entry.openuiMessageId || !sessionId) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      saveOpenUIState(
        sessionId,
        entry.openuiMessageId,
        draftState,
        summary,
      ).catch(() => {});
    }, 400);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [
    streaming,
    accepted,
    entry.openuiMessageId,
    sessionId,
    draftState,
    summary,
    saveOpenUIState,
  ]);

  useEffect(() => {
    if (streaming || reported.current || accepted || !entry.openuiMessageId)
      return;
    reported.current = true;
    reportOpenUIIssue({
      library_version: entry.libraryVersion || "unknown",
      codes:
        !versionMatches && parseStatus.errors.length === 0
          ? ["library-version-mismatch"]
          : [...new Set([...parseStatus.errors, ...rendererErrors])].length
            ? [...new Set([...parseStatus.errors, ...rendererErrors])]
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
        <p>This interactive answer could not be displayed.</p>
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
      </div>
    );
  }

  return (
    <div className="body openui-answer-body">
      <OpenUIAnswerContext.Provider value={context}>
        <Renderer
          response={entry.text}
          library={openuiLibrary}
          isStreaming={streaming}
          initialState={entry.openuiState || {}}
          onAction={action}
          onStateUpdate={onStateUpdate}
          onParseResult={onParseResult}
          onError={onRendererError}
        />
      </OpenUIAnswerContext.Provider>
      {streaming && (
        <div className="openui-pending" aria-live="polite">
          <span className="thinking-orb" aria-hidden="true" />
          <span>Preparing an interactive answer…</span>
        </div>
      )}
      {!streaming && summary && renderSpeech?.(summary)}
    </div>
  );
}
