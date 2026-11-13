// Saved history and streamed events share one React-owned conversation model.
export const initialChat = {
  id: null,
  title: "New conversation",
  entries: [],
  approvals: [],
  usage: {},
  model: "",
  reasoning: "default",
  generation: {},
  status: "",
  statusClass: "",
  busy: false,
  notice: "",
  activityId: null,
  active: null,
  output: null,
  lastAnswer: null,
  answers: [],
  sequence: 0,
  turn: 0,
  revision: 0,
};

function append(state, entry) {
  const id = "message-" + state.sequence++;
  state.entries.push({ ...entry, id });
  return id;
}

function finishActivity(state, now, durationMs) {
  if (!state.activityId) return;
  const index = state.entries.findIndex(
    (entry) => entry.id === state.activityId,
  );
  const activity = state.entries[index];
  const elapsed = Number.isFinite(durationMs)
    ? durationMs
    : now - activity.started;
  state.entries[index] = {
    ...activity,
    running: false,
    durationMs: Math.max(0, elapsed),
  };
  for (let i = index + 1; i < state.entries.length; i++) {
    const row = state.entries[i];
    if (row.kind === "compaction" && row.active)
      state.entries[i] = {
        ...row,
        active: false,
        text: "Context preparation stopped. Your conversation is saved.",
      };
  }
  state.activityId = null;
}

function assistant(state, now) {
  if (!state.active)
    state.active = append(state, {
      kind: "message",
      role: "assistant",
      text: "",
      reasoning: "",
      streaming: true,
      started: now,
      display: { created_at: now / 1000 },
      format: state.output?.format || "markdown",
      libraryVersion: state.output?.library_version || null,
      openuiMessageId: state.output?.openui_message_id || null,
      openuiState: {},
    });
  const index = state.entries.findIndex((entry) => entry.id === state.active);
  const entry = { ...state.entries[index] };
  state.entries[index] = entry;
  return entry;
}
function tool(state, call, status, content = null) {
  const callId = call.call_id ?? call.id;
  const declared = status === "queued" || status === "unresolved";
  const index = declared
    ? -1
    : state.entries.findLastIndex(
        (entry) => entry.kind === "tool" && callId && entry.callId === callId,
      );
  if (index >= 0) {
    const existing = { ...state.entries[index] };
    state.entries[index] = existing;
    existing.status = status;
    if (content !== null) existing.content = content;
    if (existing.arguments == null) existing.arguments = call.arguments ?? null;
  } else
    append(state, {
      kind: "tool",
      callId,
      name: call.name,
      status,
      content,
      arguments: call.arguments ?? null,
    });
}
function finishMessage(entry, event = {}, now) {
  entry.streaming = false;
  entry.display = {
    ...entry.display,
    duration_ms: now - entry.started,
    ...event.display,
  };
  entry.format = entry.display.format || entry.format || "markdown";
  entry.libraryVersion =
    entry.display.library_version || entry.libraryVersion || null;
  entry.openuiMessageId =
    entry.display.openui_message_id || entry.openuiMessageId || null;
  entry.openuiState = entry.display.openui_state || entry.openuiState || {};
  entry.openuiSummary =
    entry.display.openui_summary || entry.openuiSummary || "";
  entry.presentationHidden = Boolean(entry.display.openui_hidden);
  entry.requestedTools = event.requested_tools || [];
  if (entry.requestedTools.length && entry.format === "openui-lang") {
    entry.text = "";
    entry.presentationHidden = true;
  }
  entry.usage = event.usage || {};
}
function event(state, value, now) {
  if (value.type === "title") state.title = value.title;
  if (value.type === "compaction") {
    const key = value.compaction_id || value.parent_call_id || "parent";
    let row = state.entries.findLast(
      (entry) =>
        entry.kind === "compaction" &&
        entry.compactionKey === key &&
        entry.turn === state.turn,
    );
    if (!row || value.status === "started") {
      const id = append(state, {
        kind: "compaction",
        compactionKey: key,
        turn: state.turn,
      });
      row = state.entries.find((entry) => entry.id === id);
    }
    row = { ...row };
    state.entries[state.entries.findIndex((entry) => entry.id === row.id)] =
      row;
    row.active = ["started", "progress"].includes(value.status);
    row.text = row.active
      ? value.parent_call_id
        ? "Organizing research context…"
        : "Organizing earlier conversation…"
      : value.status === "completed"
        ? "Context ready. Continuing."
        : "Context preparation stopped. Your conversation is saved.";
  }
  if (value.type === "thinking") {
    const entry = assistant(state, now);
    entry.started = now;
    entry.display = { ...entry.display, ...value.display };
  }
  if (value.type === "assistant_format") {
    state.output = value;
    if (state.active) {
      const entry = assistant(state, now);
      entry.format = value.format;
      entry.libraryVersion = value.library_version;
      entry.openuiMessageId = value.openui_message_id;
    }
  }
  if (value.type === "text") assistant(state, now).text += value.text;
  if (value.type === "reasoning") {
    const entry = assistant(state, now);
    entry.reasoning += value.text;
  }
  if (value.type === "answer_replace") {
    if (!state.active && state.lastAnswer) state.active = state.lastAnswer;
    state.entries = state.entries.flatMap((entry) => {
      if (!state.answers.includes(entry.id) || entry.id === state.active)
        return [entry];
      return entry.reasoning
        ? [{ ...entry, text: "", presentationHidden: true }]
        : [];
    });
    state.answers = [];
  }
  if (["assistant_complete", "answer_replace"].includes(value.type)) {
    if (value.text || value.reasoning || state.active) {
      const entry = assistant(state, now);
      entry.text = value.text || "";
      // Preserve a streamed reasoning summary when the completion omits it.
      entry.reasoning = value.reasoning || entry.reasoning;
      finishMessage(entry, value, now);
      if (!entry.text && !entry.reasoning)
        state.entries = state.entries.filter((row) => row.id !== entry.id);
      else if (!value.requested_tools?.length) {
        state.lastAnswer = entry.id;
        state.answers.push(entry.id);
      }
    }
    for (const call of value.tool_calls || []) tool(state, call, "queued");
    state.active = null;
    state.output = null;
  }
  if (value.type === "tool") {
    tool(state, value, value.status, value.content ?? null);
  }
  if (value.type === "file") append(state, { kind: "file", ...value });
  if (value.type === "approvals") {
    state.approvals = value.items;
    const pending = new Set(value.items.map((item) => item.call_id));
    state.entries = state.entries.map((entry) =>
      entry.kind === "tool" && pending.has(entry.callId)
        ? { ...entry, status: "waiting_for_approval" }
        : entry,
    );
  }
  if (value.type === "error") {
    finishActivity(state, now);
    state.status = value.message;
    state.statusClass = "error";
  }
  if (value.type === "done") finishActivity(state, now, value.duration_ms);
}
export function historyEntries(session) {
  const state = { ...initialChat, entries: [], sequence: 0 };
  const pending = new Set(session.approvals.map((item) => item.call_id));
  for (const message of session.history) {
    const activity = message.display?.turn_activity;
    if (activity && message.type !== "user")
      append(state, { kind: "activity", durationMs: activity.duration_ms });
    if (message.type === "user") {
      append(state, {
        kind: "message",
        role: "user",
        text: message.display?.user_text || message.content,
        images: message.images,
        display: message.display,
      });
      if (activity)
        append(state, { kind: "activity", durationMs: activity.duration_ms });
    }
    if (message.type === "assistant") {
      const hidden =
        message.display?.openui_hidden || message.display?.superseded;
      if (message.reasoning || (message.text && !hidden))
        append(state, {
          kind: "message",
          role: "assistant",
          text: hidden ? "" : message.text || "",
          reasoning: message.reasoning || "",
          display: message.display,
          usage: message.usage,
          format: message.display?.format || "markdown",
          libraryVersion: message.display?.library_version || null,
          openuiMessageId: message.display?.openui_message_id || null,
          openuiState: message.display?.openui_state || {},
          openuiSummary: message.display?.openui_summary || "",
          presentationHidden: Boolean(hidden),
        });
      for (const call of message.tool_calls || [])
        tool(state, call, "unresolved");
    }
    if (message.type === "tool_result") {
      tool(state, message, message.status, message.content);
      if (message.status === "completed") {
        try {
          const result = JSON.parse(message.content);
          if (result?.file_id) append(state, { kind: "file", ...result });
        } catch {}
      }
    }
  }
  state.entries = state.entries.map((entry) =>
    entry.kind === "tool" &&
    entry.status === "unresolved" &&
    pending.has(entry.callId)
      ? { ...entry, status: "waiting_for_approval" }
      : entry,
  );
  return state;
}

export function conversationEntries(entries) {
  const transcript = [];
  let activity;
  // The marker comes from Send during streaming and from saved history after reload.
  // Older conversations can group their available activity between user messages.
  for (const entry of entries) {
    if (entry.kind === "activity") {
      activity = { ...entry, rows: [] };
      transcript.push(activity);
      continue;
    }
    if (entry.role === "user" && !entry.display?.workspace_inspection)
      activity = null;
    if (
      entry.reasoning ||
      entry.kind === "tool" ||
      entry.kind === "compaction"
    ) {
      if (!activity) {
        activity = { id: "activity-" + entry.id, kind: "activity", rows: [] };
        transcript.push(activity);
      }
      activity.rows.push(entry);
    }
    if (
      entry.kind === "file" ||
      (entry.kind === "message" &&
        (entry.role !== "assistant" ||
          (entry.text && !entry.presentationHidden)))
    )
      transcript.push(entry);
  }
  return transcript.filter(
    (entry) =>
      entry.kind !== "activity" ||
      entry.running ||
      Number.isFinite(entry.durationMs) ||
      entry.rows.length,
  );
}

export function chatReducer(previous, action) {
  const now = action.now ?? 0;
  if (action.type === "LOAD")
    return {
      ...initialChat,
      ...historyEntries(action.session),
      revision: previous.revision + 1,
      id: action.session.id,
      title: action.session.title,
      model: action.session.model,
      reasoning: action.session.reasoning,
      generation: action.session.generation,
      usage: action.session.usage,
      approvals: action.session.approvals,
      notice:
        action.session.status === "running"
          ? "This turn is still running. Reopen the conversation to load its result."
          : "",
    };
  if (action.sessionId && action.sessionId !== previous.id) return previous;
  const state = {
    ...previous,
    entries: [...previous.entries],
    answers: [...previous.answers],
  };
  if (action.type === "USER")
    append(state, {
      kind: "message",
      role: "user",
      text: action.text,
      display: { created_at: now / 1000 },
    });
  if (action.type === "START") {
    state.turn++;
    state.activityId = append(state, {
      kind: "activity",
      running: true,
      started: now,
    });
    state.busy = true;
    state.notice = "";
    state.active = null;
    state.output = null;
    state.lastAnswer = null;
    state.answers = [];
    state.status = "";
    state.statusClass = "";
    assistant(state, now);
  }
  if (action.type === "EVENTS")
    for (const value of action.events) event(state, value, now);
  if (action.type === "FINISH") {
    finishActivity(state, now);
    state.entries = state.entries.map((previous) => {
      if (!previous.streaming) return previous;
      const entry = { ...previous };
      finishMessage(entry, {}, now);
      return entry;
    });
    state.entries = state.entries.filter(
      (entry) =>
        entry.kind !== "message" ||
        entry.role !== "assistant" ||
        entry.text ||
        entry.reasoning,
    );
    state.busy = false;
    state.active = null;
    state.output = null;
    if (state.statusClass !== "error") state.statusClass = "";
  }
  if (action.type === "SYNC") {
    Object.assign(state, action.values);
    state.entries = previous.entries;
  }
  if (action.type === "STATUS") {
    state.status = action.text;
    state.statusClass = action.className || "";
    state.entries = previous.entries;
  }
  if (action.type === "APPROVAL_ACCEPTED") {
    state.approvals = state.approvals.filter(
      (item) => item.id !== action.item.id,
    );
    tool(
      state,
      { call_id: action.item.call_id, name: action.item.tool },
      action.approved ? "approved" : "denied",
    );
  }
  return state;
}
export function formatCost(usage = {}) {
  if (!usage.requests) return "$0.00";
  if (usage.cost === null) return "Unavailable";
  const cost = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(usage.cost);
  return usage.unpriced_requests ? cost + " (partial)" : cost;
}

// Decode network frames independently of React renders. Never replay a request.
export async function readEvents(response, receive) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    finished = false,
    ended = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replaceAll("\r\n", "\n");
      let index;
      while ((index = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!data) continue;
        const event = JSON.parse(data);
        if (event.type === "done") finished = true;
        receive(event);
      }
      if (done) {
        ended = true;
        break;
      }
    }
    if (!finished)
      throw new Error(
        "The connection ended. Reopen the conversation to inspect its saved result before you retry.",
      );
  } finally {
    if (!ended) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
