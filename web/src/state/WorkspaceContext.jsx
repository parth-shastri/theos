"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import { conversationsReducer, initialConversations, readEvents } from "./chat";
import { commands } from "./config";

const Context = createContext(null);
export const useWorkspace = () => useContext(Context);

export function WorkspaceProvider({ agentName, children }) {
  const [{ selected: chat, background, unread }, reduce] = useReducer(
    conversationsReducer,
    initialConversations,
  );
  const dispatch = useCallback(
    (action) => reduce({ ...action, now: Date.now() }),
    [],
  );
  const [me, setMe] = useState(null);
  const [notificationPermission, setNotificationPermission] = useState(null);
  const [responseNotifications, setResponseNotifications] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [usage, setUsage] = useState({});
  const [working, setWorking] = useState(false);
  const [view, setView] = useState("chat-view");
  const [dialog, setDialog] = useState(null);
  const [connections, setConnections] = useState(null);
  const [journey, setJourney] = useState(null);
  const [journeyWorking, setJourneyWorking] = useState(false);
  const [journeyError, setJourneyError] = useState("");
  const [accountSetup, setAccountSetup] = useState(null);
  const [theme, setTheme] = useState(null);
  const [mobile, setMobile] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [workspacePanel, setWorkspacePanel] = useState(null);
  const [panelHeadingHost, setPanelHeadingHost] = useState(null);
  const [desktopPanelHeadingHost, setDesktopPanelHeadingHost] = useState(null);
  const [draftRequest, setDraftRequest] = useState(null);
  const [autoPlay, setAutoPlay] = useState(null);
  const [loginError, setLoginError] = useState("");
  const [signingIn, setSigningIn] = useState(false);
  const [onboarding, setOnboarding] = useState(null);
  const lifetime = useRef(null);
  const accountLifetime = useRef(null);
  const selectionRequest = useRef(0);
  const sessionsRequest = useRef(0);
  const dialogRequest = useRef(0);
  const streamLocks = useRef(new Map());
  const signinTimer = useRef(null);
  const current = useRef({});
  current.current = {
    me,
    chat,
    background,
    view,
    working,
    mobile,
    dialog,
    connections,
    journey,
    journeyWorking,
  };

  const status = useCallback(
    (text, className = "", sessionId) =>
      dispatch({ type: "STATUS", text, className, sessionId }),
    [],
  );
  const showError = useCallback(
    (error) => {
      if (error.name !== "AbortError") status(error.message, "error");
    },
    [status],
  );
  const api = useCallback(async (path, options = {}) => {
    const controller = lifetime.current;
    const account = accountLifetime.current;
    const headers = { "X-Theos-Request": "1", ...options.headers };
    let body = options.body;
    if (body != null && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      if (typeof body !== "string") body = JSON.stringify(body);
    }
    const response = await fetch(path, {
      ...options,
      body,
      headers,
      signal: AbortSignal.any([
        controller.signal,
        account.signal,
        ...(options.signal ? [options.signal] : []),
      ]),
    });
    if (!response.ok) {
      let detail = "The request failed. Please try again.";
      try {
        const value = await response.json();
        if (typeof value.detail === "string") detail = value.detail;
      } catch {}
      const error = new Error(detail);
      error.status = response.status;
      if (
        response.status === 401 &&
        current.current.me &&
        account === accountLifetime.current &&
        !account.signal.aborted
      ) {
        account.abort();
        accountLifetime.current = new AbortController();
        selectionRequest.current++;
        setMe(null);
        setSidebarOpen(false);
        setWorkspacePanel(null);
        setDialog(null);
        setSessions([]);
        streamLocks.current.clear();
        dispatch({ type: "CLEAR_CONVERSATIONS" });
        setLoginError("Your session expired. Sign in again.");
      }
      throw error;
    }
    return response;
  }, []);
  const json = useCallback(
    async (path, options) => {
      const account = accountLifetime.current;
      const value = await (await api(path, options)).json();
      if (account !== accountLifetime.current || account.signal.aborted)
        throw new DOMException("The request was canceled.", "AbortError");
      return value;
    },
    [api],
  );
  const perform = useCallback(
    (action) => Promise.resolve().then(action).catch(showError),
    [showError],
  );
  const navigate = useCallback((next) => {
    selectionRequest.current++;
    setView(next);
    if (current.current.mobile) setSidebarOpen(false);
    setWorkspacePanel(null);
  }, []);
  const editDraft = useCallback(
    (text, suggest = false) => {
      navigate("chat-view");
      setDraftRequest({ text, suggest, id: Date.now() + Math.random() });
    },
    [navigate],
  );
  const listSessions = useCallback(async () => {
    const request = ++sessionsRequest.current;
    const result = await json("/api/sessions");
    if (request === sessionsRequest.current) setSessions(result);
    return result;
  }, [json]);
  const refreshConnections = useCallback(async () => {
    const result = await json("/api/connections");
    setConnections(result);
    return result;
  }, [json]);
  const syncUsage = useCallback((session, usage) => {
    dispatch({
      type: "SYNC",
      sessionId: session.id,
      values: { usage: session.usage },
    });
    setUsage(usage);
  }, []);
  const openSession = useCallback(
    async (id) => {
      navigate("chat-view");
      const request = selectionRequest.current;
      const { chat, background } = current.current;
      if (chat.id === id && (chat.busy || streamLocks.current.has(id))) return;
      let session = null;
      if (!background.has(id)) {
        try {
          session = await json("/api/sessions/" + id);
        } catch (error) {
          if (request === selectionRequest.current) throw error;
          return;
        }
      }
      if (request !== selectionRequest.current) return;
      dispatch({ type: "SELECT_CONVERSATION", sessionId: id, session });
      setAutoPlay(null);
      await Promise.all([listSessions(), json("/api/usage").then(setUsage)]);
    },
    [json, listSessions, navigate],
  );
  const newSession = useCallback(async () => {
    const request = ++selectionRequest.current;
    const result = await json("/api/sessions", {
      method: "POST",
      body: { title: "New conversation" },
    });
    if (request !== selectionRequest.current) {
      await listSessions();
      return;
    }
    const selection = openSession(result.id);
    const openRequest = selectionRequest.current;
    await selection;
    if (openRequest === selectionRequest.current) editDraft("");
  }, [json, listSessions, openSession, editDraft]);
  const login = useCallback(async () => {
    const identity = await json("/api/me");
    setJourney(identity.journey || null);
    setJourneyError("");
    setAccountSetup(null);
    dispatch({ type: "CLEAR_CONVERSATIONS" });
    setLoginError("");
    const available = await listSessions();
    const params = new URLSearchParams(location.search);
    const requested = params.get("conversation");
    if (requested && available.some((session) => session.id === requested))
      await openSession(requested);
    else if (available.length) await openSession(available[0].id);
    else await newSession();
    try {
      const accounts = await refreshConnections();
      if (params.get("connections") === "1") navigate("connections-view");
      const connected = params.get("connected") || params.get("connect");
      if (
        connected &&
        accounts.accounts.some((account) => account.id === connected)
      )
        setAccountSetup({
          service: connected,
          sessionId: current.current.chat.id,
        });
      if (params.has("connections")) {
        params.delete("connections");
        history.replaceState(
          null,
          "",
          location.pathname + (params.size ? "?" + params : "") + location.hash,
        );
      }
    } catch {}
    setMe(identity);
  }, [
    json,
    listSessions,
    newSession,
    openSession,
    refreshConnections,
    navigate,
  ]);
  const advanceJourney = async (action, value = "") => {
    if (current.current.journeyWorking) return;
    setJourneyWorking(true);
    setJourneyError("");
    try {
      const next = await json("/api/journey", {
        method: "POST",
        body: { action, value, revision: current.current.journey.revision },
      });
      setJourney(next);
      setMe((previous) => ({
        ...previous,
        display_name: next.display_name,
        timezone: next.timezone,
      }));
      return next;
    } catch (error) {
      if (error.name !== "AbortError") {
        setJourneyError(error.message);
        const latest = await json("/api/journey");
        setJourney(latest);
      }
      throw error;
    } finally {
      setJourneyWorking(false);
    }
  };
  const finishConnectionSetup = async (profile = {}) => {
    const result = await json("/api/connections/onboarding", {
      method: "POST",
      body: profile,
    });
    setMe((value) => ({ ...value, ...result }));
    await refreshConnections();
    navigate("chat-view");
  };
  const signIn = async (credentials, passwordAction) => {
    setSigningIn(true);
    setLoginError("");
    try {
      await json(
        "account" in credentials
          ? "/api/auth/password/login"
          : "/api/auth/login",
        { method: "POST", body: credentials },
      );
      if (passwordAction) {
        setOnboarding({ passwordAction, status: "Access token verified." });
      } else await login();
    } catch (error) {
      if (error.name !== "AbortError") setLoginError(error.message);
    } finally {
      setSigningIn(false);
    }
  };
  const clearLoginError = () => setLoginError("");
  const signOut = () =>
    perform(async () => {
      await json("/api/auth/logout", { method: "POST" });
      accountLifetime.current.abort();
      accountLifetime.current = new AbortController();
      selectionRequest.current++;
      setMe(null);
      setSidebarOpen(false);
      setWorkspacePanel(null);
      setSessions([]);
      setDialog(null);
      setOnboarding(null);
      setJourney(null);
      setJourneyError("");
      setAccountSetup(null);
      setConnections(null);
      streamLocks.current.clear();
      dispatch({ type: "CLEAR_CONVERSATIONS" });
    });

  const notifyCompletion = useCallback(
    (sessionId, accountId) => {
      if (
        typeof Notification === "undefined" ||
        Notification.permission !== "granted" ||
        localStorage.getItem("theos-response-notifications-" + accountId) ===
          "off"
      )
        return;
      try {
        const notification = new Notification("Theos response ready", {
          tag: "theos-response-" + sessionId,
          icon: "/static/brand.png",
        });
        notification.onclick = () => {
          notification.close();
          if (current.current.me?.id !== accountId) return;
          window.focus();
          void openSession(sessionId).catch(showError);
        };
      } catch {
        // Some browsers expose Notification but only support service worker delivery.
      }
    },
    [openSession, showError],
  );

  const stream = useCallback(
    async (sessionId, path, payload, { approval, text } = {}) => {
      if (!sessionId || streamLocks.current.has(sessionId)) return;
      const accountId = current.current.me?.id;
      const signal = AbortSignal.any([
        lifetime.current.signal,
        accountLifetime.current.signal,
      ]);
      streamLocks.current.set(sessionId, signal);
      if (text !== undefined) dispatch({ type: "USER", sessionId, text });
      dispatch({ type: "START", sessionId });
      let queue = [];
      let frame = null;
      const flush = () => {
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        if (!signal.aborted && queue.length)
          dispatch({ type: "EVENTS", sessionId, events: queue });
        queue = [];
      };
      let synced = false;
      let responseReceived = false;
      let completed = false;
      try {
        const response = await api(path, { method: "POST", body: payload });
        responseReceived = true;
        if (approval && !signal.aborted)
          dispatch({ type: "APPROVAL_ACCEPTED", sessionId, ...approval });
        await readEvents(response, (event) => {
          if (signal.aborted) return;
          if (event.type === "done") {
            if (
              !completed &&
              event.status === "completed" &&
              (current.current.chat.id !== sessionId ||
                current.current.view !== "chat-view" ||
                document.hidden)
            ) {
              dispatch({ type: "UNREAD", sessionId });
              notifyCompletion(sessionId, accountId);
            }
            completed = true;
          }
          queue.push(event);
          if (frame === null) frame = requestAnimationFrame(flush);
        });
        flush();
        if (signal.aborted) return;
        const session = await json("/api/sessions/" + sessionId);
        dispatch({
          type: "SYNC",
          sessionId,
          values: {
            title: session.title,
            usage: session.usage,
            approvals: session.approvals,
          },
        });
        synced = true;
        await Promise.all([listSessions(), json("/api/usage").then(setUsage)]);
        if (
          !signal.aborted &&
          session.status === "completed" &&
          current.current.chat.id === sessionId &&
          current.current.view === "chat-view" &&
          !document.hidden &&
          sessionStorage.getItem("theos-tts-" + accountId) === "true"
        )
          setAutoPlay({ sessionId, request: Date.now() });
      } catch (error) {
        if (signal.aborted || error.name === "AbortError") return;
        if (responseReceived && !completed) {
          flush();
          try {
            const session = await json("/api/sessions/" + sessionId);
            dispatch({ type: "RELOAD", sessionId, session });
            status(
              "The connection ended. The saved conversation is loaded. Review it before trying again.",
              "",
              sessionId,
            );
            synced = true;
            await listSessions();
          } catch (reloadError) {
            if (!signal.aborted && reloadError.name !== "AbortError")
              status(reloadError.message, "error", sessionId);
          }
          return;
        }
        status(error.message, "error", sessionId);
      } finally {
        flush();
        if (!synced && !signal.aborted) {
          try {
            const session = await json("/api/sessions/" + sessionId);
            dispatch({
              type: "SYNC",
              sessionId,
              values: { approvals: session.approvals },
            });
          } catch {}
        }
        if (!signal.aborted) dispatch({ type: "FINISH", sessionId });
        if (streamLocks.current.get(sessionId) === signal)
          streamLocks.current.delete(sessionId);
      }
    },
    [api, json, listSessions, notifyCompletion, status],
  );
  const openUIAction = useCallback(
    async (sessionId, payload) => {
      if (sessionId !== current.current.chat.id) return;
      const { visible_text, ...request } = payload;
      const text = (
        visible_text ||
        request.label ||
        "Continue this conversation"
      ).slice(0, 500);
      await stream(
        sessionId,
        "/api/sessions/" + sessionId + "/openui-actions",
        request,
        { text },
      );
    },
    [stream],
  );
  const saveOpenUIState = useCallback(
    async (sessionId, messageId, state, summary) => {
      await json("/api/sessions/" + sessionId + "/openui-state", {
        method: "PUT",
        body: { message_id: messageId, state, summary },
      });
    },
    [json],
  );
  const reportOpenUIIssue = useCallback(
    async (issue) => {
      await json("/api/openui/issues", { method: "POST", body: issue });
    },
    [json],
  );
  const send = async (text, files, mode) => {
    const { id } = current.current.chat;
    if (current.current.journey?.needed) {
      if (!files?.length) return advanceJourney("reply", text);
      await advanceJourney("finish");
    }
    const connection = text
      .trim()
      .match(
        /^(?:please\s+)?(?:connect|link|set up)\s+(?:my\s+)?(gmail|google calendar|calendar|google health|health|github|slack|zepto|telegram calls|calls)[.!]?$/i,
      );
    if (connection && !files?.length) {
      const service = connection[1]
        .toLowerCase()
        .replace("google ", "")
        .replace("telegram ", "");
      await refreshConnections();
      setAccountSetup({ service, sessionId: id });
      return;
    }
    return stream(
      id,
      "/api/sessions/" + id + "/turn",
      { text, files, mode },
      { text },
    );
  };
  const resume = () => {
    const { id } = current.current.chat;
    navigate("chat-view");
    return stream(id, "/api/sessions/" + id + "/resume");
  };
  const reset = async () => {
    const { id } = current.current.chat;
    if (!id || streamLocks.current.has(id)) return;
    if (
      !window.confirm(
        "Reset this conversation? Saved records and files remain available.",
      )
    )
      return;
    const request = selectionRequest.current;
    await json("/api/sessions/" + id + "/reset", { method: "POST" });
    if (request === selectionRequest.current) await openSession(id);
  };
  const approve = (item, approved) => {
    const { id } = current.current.chat;
    return stream(
      id,
      "/api/sessions/" + id + "/approvals/" + item.id,
      { approved },
      { approval: { item, approved } },
    );
  };
  const patchSettings = async (values) => {
    const id = current.current.chat.id;
    const result = await json("/api/sessions/" + id, {
      method: "PATCH",
      body: values,
    });
    dispatch({
      type: "SYNC",
      sessionId: id,
      values: {
        model: result.model ?? values.model,
        reasoning: result.reasoning ?? values.reasoning,
        generation: result.generation,
      },
    });
    status("Settings saved.", "", id);
  };
  const openDialog = (kind, section = "") => {
    const { chat, working, mobile } = current.current;
    if (
      kind !== "password" &&
      (!chat.id ||
        working ||
        (kind === "settings" && streamLocks.current.has(chat.id)))
    )
      return;
    if (mobile) setSidebarOpen(false);
    setWorkspacePanel(null);
    setDialog({ kind, section, request: ++dialogRequest.current });
  };
  const closeDialog = useCallback(() => {
    dialogRequest.current++;
    setDialog(null);
  }, []);
  const runCommand = async (text) => {
    const [command, ...parts] = text.slice(1).split(/\s+/);
    const argument = parts.join(" ").trim();
    const name =
      command.toLowerCase() === "thinking"
        ? "reasoning"
        : command.toLowerCase();
    const spec = commands.find((item) => item.name === name);
    if (!spec)
      throw new Error(
        "Unknown command /" +
          command +
          ". Use /help to see available commands.",
      );
    if (!spec.argument && argument)
      throw new Error(
        "/" + name + " takes no arguments. Use /help for command syntax.",
      );
    if (name === "research") {
      if (!argument)
        throw new Error("Use /research followed by your question.");
      return send(argument, [], "deep_research");
    }
    if (name === "new") return newSession();
    if (name === "reset") return reset();
    if (name === "resume") return resume();
    if (name === "tools" || name === "connections")
      return navigate(name + "-view");
    if (["help", "usage", "settings", "voice"].includes(name))
      return openDialog(
        name === "voice" ? "settings" : name,
        name === "voice" ? "voice" : "",
      );
    if (!argument) return editDraft("/" + name + " ", true);
    const currentChat = current.current.chat;
    const values =
      name === "model"
        ? current.current.me.models
        : current.current.me.generation_capabilities[currentChat.model]
            ?.reasoning || ["default"];
    if (!values.includes(argument))
      throw new Error("Choose one of: " + values.join(", "));
    const model = name === "model" ? argument : currentChat.model;
    const choices = current.current.me.generation_capabilities[model]
      ?.reasoning || ["default"];
    const reasoning =
      name === "reasoning"
        ? argument
        : choices.includes(currentChat.reasoning)
          ? currentChat.reasoning
          : "default";
    setWorking(true);
    try {
      await patchSettings({ model, reasoning });
      status(
        (name === "model" ? "Model" : "Reasoning effort") +
          " saved: " +
          argument,
        "",
        currentChat.id,
      );
    } finally {
      setWorking(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    accountLifetime.current = new AbortController();
    sessionStorage.removeItem("theos-token");
    const themePreference = localStorage.getItem("theos-theme");
    setTheme(
      ["light", "dark"].includes(themePreference)
        ? themePreference
        : matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light",
    );
    const media = matchMedia("(max-width: 700px)");
    const resize = () => {
      setMobile(media.matches);
      setSidebarOpen(false);
      setWorkspacePanel(null);
    };
    resize();
    media.addEventListener("change", resize);
    const signinError = (error) => {
      if (!controller.signal.aborted && error.name !== "AbortError")
        setOnboarding((value) => ({ ...value, error: error.message }));
    };
    const pollSignin = async () => {
      const result = await json("/api/onboarding/status");
      if (controller.signal.aborted) return;
      setOnboarding((value) => ({ ...value, code: result.code }));
      if (result.state === "approved") {
        const access = await json("/api/onboarding/complete", {
          method: "POST",
        });
        sessionStorage.removeItem("theos-pending-signin");
        setOnboarding({
          account: access.id,
          token: access.token,
          status: "Telegram confirmed this browser.",
        });
      } else if (result.state === "pending")
        signinTimer.current = setTimeout(
          () => pollSignin().catch(signinError),
          2000,
        );
      else
        throw new Error(
          "This sign-in was denied or already used. Send /web in Telegram for a new link.",
        );
    };
    const initialize = async () => {
      const invite = new URLSearchParams(location.hash.slice(1)).get("onboard");
      if (invite) {
        history.replaceState(null, "", location.pathname + location.search);
        setOnboarding({ status: "Preparing your sign-in…" });
        const result = await json("/api/onboarding/start", {
          method: "POST",
          body: { invite },
        });
        sessionStorage.setItem("theos-pending-signin", "1");
        setOnboarding({
          code: result.code,
          status:
            "Waiting for your confirmation in Telegram. Confirm before " +
            new Date(result.expires * 1000).toLocaleTimeString() +
            ".",
        });
        await pollSignin();
      } else if (sessionStorage.getItem("theos-pending-signin")) {
        setOnboarding({ status: "Waiting for your confirmation in Telegram." });
        await pollSignin();
      } else await login();
    };
    initialize().catch((error) => {
      if (controller.signal.aborted || error.name === "AbortError") return;
      if (sessionStorage.getItem("theos-pending-signin")) signinError(error);
      else if (error.status !== 401) setLoginError(error.message);
    });
    const hash = () => {
      if (new URLSearchParams(location.hash.slice(1)).has("onboard"))
        location.reload();
    };
    window.addEventListener("hashchange", hash);
    return () => {
      controller.abort();
      clearTimeout(signinTimer.current);
      media.removeEventListener("change", resize);
      window.removeEventListener("hashchange", hash);
    };
  }, [json, login]);
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    if (!me?.id || !me.journey) return;
    const refresh = async () => {
      if (current.current.journeyWorking) return;
      try {
        const next = await json("/api/journey");
        setJourney(next);
      } catch {}
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [me?.id, me?.journey, json]);
  useEffect(() => {
    if (!me || !connections) return;
    const service = sessionStorage.getItem("theos-connection-window");
    const account = connections.accounts.find(
      (account) => account.id === service,
    );
    if (
      account?.connected &&
      !["starting", "waiting", "failed", "expired"].includes(
        account.setup.status,
      )
    ) {
      sessionStorage.removeItem("theos-connection-window");
      window.close();
    }
  }, [me, connections]);
  useEffect(() => {
    const markRead = () => {
      if (chat.id && view === "chat-view" && !document.hidden)
        dispatch({ type: "READ", sessionId: chat.id });
    };
    markRead();
    document.addEventListener("visibilitychange", markRead);
    return () => document.removeEventListener("visibilitychange", markRead);
  }, [chat.id, view]);

  useEffect(() => {
    const refresh = () => {
      const permission =
        typeof Notification === "undefined" ? null : Notification.permission;
      setNotificationPermission(permission);
      setResponseNotifications(
        permission === "granted" &&
          localStorage.getItem("theos-response-notifications-" + me?.id) !==
            "off",
      );
    };
    refresh();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [me?.id]);

  const toggleResponseNotifications = async () => {
    const accountId = me?.id;
    const key = "theos-response-notifications-" + accountId;
    if (!accountId || typeof Notification === "undefined") return;
    if (responseNotifications) {
      localStorage.setItem(key, "off");
      setResponseNotifications(false);
      return;
    }
    const permission =
      Notification.permission === "default"
        ? await Notification.requestPermission()
        : Notification.permission;
    if (current.current.me?.id !== accountId) return;
    setNotificationPermission(permission);
    if (permission === "granted") {
      localStorage.removeItem(key);
      setResponseNotifications(true);
    }
  };
  const toggleTheme = () =>
    setTheme((value) => {
      const next = value === "dark" ? "light" : "dark";
      localStorage.setItem("theos-theme", next);
      return next;
    });
  const cancelSignin = () =>
    perform(async () => {
      clearTimeout(signinTimer.current);
      await json("/api/onboarding/cancel", { method: "POST" });
      sessionStorage.removeItem("theos-pending-signin");
      setOnboarding(null);
    });
  const finishSignin = async () => {
    const account = accountLifetime.current;
    setSigningIn(true);
    try {
      await login();
      if (account === accountLifetime.current && !account.signal.aborted)
        setOnboarding(null);
    } catch (error) {
      if (account === accountLifetime.current && !account.signal.aborted)
        setOnboarding((value) => ({ ...value, error: error.message }));
    } finally {
      setSigningIn(false);
    }
  };
  return (
    <Context.Provider
      value={{
        agentName,
        me,
        panelHeadingHost,
        setPanelHeadingHost,
        desktopPanelHeadingHost,
        setDesktopPanelHeadingHost,
        chat,
        sessions,
        unread,
        notificationPermission,
        responseNotifications,
        toggleResponseNotifications,
        usage,
        working,
        setWorking,
        busy: chat.busy || working || journeyWorking,
        view,
        navigate,
        dialog,
        openDialog,
        closeDialog,
        mobile,
        sidebarOpen,
        setSidebarOpen,
        workspacePanel,
        setWorkspacePanel,
        theme: theme ?? "light",
        brand:
          theme === "dark" ? "/static/brand.png" : "/static/brand-light.png",
        toggleTheme,
        draftRequest,
        editDraft,
        autoPlay,
        api,
        json,
        perform,
        status,
        showError,
        connections,
        journey,
        journeyWorking,
        journeyError,
        advanceJourney,
        accountSetup,
        setAccountSetup,
        refreshConnections,
        finishConnectionSetup,
        syncUsage,
        openSession,
        newSession,
        send,
        openUIAction,
        saveOpenUIState,
        reportOpenUIIssue,
        resume,
        reset,
        approve,
        patchSettings,
        runCommand,
        loginError,
        clearLoginError,
        signingIn,
        signIn,
        signOut,
        onboarding,
        finishSignin,
        cancelSignin,
      }}
    >
      {children}
    </Context.Provider>
  );
}
