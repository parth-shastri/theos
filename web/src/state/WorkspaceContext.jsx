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
import { chatReducer, initialChat, readEvents } from "./chat";
import { commands } from "./config";

const Context = createContext(null);
export const useWorkspace = () => useContext(Context);

export function WorkspaceProvider({ agentName, children }) {
  const [chat, reduce] = useReducer(chatReducer, initialChat);
  const dispatch = useCallback(
    (action) => reduce({ ...action, now: Date.now() }),
    [],
  );
  const [me, setMe] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [usage, setUsage] = useState({});
  const [working, setWorking] = useState(false);
  const [view, setView] = useState("chat-view");
  const [dialog, setDialog] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [connections, setConnections] = useState(null);
  const [theme, setTheme] = useState("light");
  const [mobile, setMobile] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
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
  const dialogRequest = useRef(0);
  const streamLock = useRef(false);
  const signinTimer = useRef(null);
  const current = useRef({});
  current.current = { me, chat, working, mobile, dialog, connections };

  const status = useCallback(
    (text, className = "") => dispatch({ type: "STATUS", text, className }),
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
      if (response.status === 401 && current.current.me) {
        account.abort();
        accountLifetime.current = new AbortController();
        selectionRequest.current++;
        setMe(null);
        setDialog(null);
        setSessions([]);
        dispatch({
          type: "LOAD",
          session: { ...initialChat, history: [], approvals: [] },
        });
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
    setView(next);
    if (current.current.mobile) setSidebarOpen(false);
  }, []);
  const editDraft = useCallback(
    (text, suggest = false) => {
      navigate("chat-view");
      setDraftRequest({ text, suggest, id: Date.now() + Math.random() });
    },
    [navigate],
  );
  const listSessions = useCallback(async () => {
    const result = await json("/api/sessions");
    setSessions(result);
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
      if (streamLock.current) return;
      const request = ++selectionRequest.current;
      navigate("chat-view");
      const result = await json("/api/sessions/" + id);
      if (request !== selectionRequest.current) return;
      dispatch({ type: "LOAD", session: result });
      setAutoPlay(null);
      await Promise.all([listSessions(), json("/api/usage").then(setUsage)]);
    },
    [json, listSessions, navigate],
  );
  const newSession = useCallback(async () => {
    const result = await json("/api/sessions", {
      method: "POST",
      body: { title: "New conversation" },
    });
    await openSession(result.id);
    editDraft("");
  }, [json, openSession, editDraft]);
  const login = useCallback(async () => {
    const identity = await json("/api/me");
    dispatch({
      type: "LOAD",
      session: { ...initialChat, history: [], approvals: [] },
    });
    setMe(identity);
    setLoginError("");
    const available = await listSessions();
    if (available.length) await openSession(available[0].id);
    else await newSession();
    refreshConnections().catch(() => {});
  }, [json, listSessions, newSession, openSession, refreshConnections]);
  const signIn = async (token) => {
    setSigningIn(true);
    setLoginError("");
    try {
      await json("/api/auth/login", {
        method: "POST",
        body: { token: token.trim() },
      });
      await login();
    } catch (error) {
      if (error.name !== "AbortError") setLoginError(error.message);
    } finally {
      setSigningIn(false);
    }
  };
  const signOut = () =>
    perform(async () => {
      await json("/api/auth/logout", { method: "POST" });
      accountLifetime.current.abort();
      accountLifetime.current = new AbortController();
      selectionRequest.current++;
      setMe(null);
      setSessions([]);
      setDialog(null);
      setOnboarding(null);
      dispatch({
        type: "LOAD",
        session: { ...initialChat, history: [], approvals: [] },
      });
    });

  const stream = useCallback(
    async (path, payload, approval) => {
      if (streamLock.current) return;
      streamLock.current = true;
      const sessionId = current.current.chat.id;
      const signal = AbortSignal.any([
        lifetime.current.signal,
        accountLifetime.current.signal,
      ]);
      dispatch({ type: "START", sessionId });
      let queue = [],
        frame = null;
      const flush = () => {
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        if (!signal.aborted && queue.length)
          dispatch({ type: "EVENTS", sessionId, events: queue });
        queue = [];
      };
      let synced = false;
      try {
        const response = await api(path, { method: "POST", body: payload });
        if (approval)
          dispatch({ type: "APPROVAL_ACCEPTED", sessionId, ...approval });
        await readEvents(response, (event) => {
          queue.push(event);
          if (frame === null) frame = requestAnimationFrame(flush);
        });
        flush();
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
          session.status === "completed" &&
          sessionStorage.getItem("theos-tts-" + current.current.me?.id) ===
            "true"
        )
          setAutoPlay({ sessionId, request: Date.now() });
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
        dispatch({ type: "FINISH", sessionId });
        streamLock.current = false;
      }
    },
    [api, json, listSessions],
  );
  const send = async (text, files, mode) => {
    if (streamLock.current) return;
    dispatch({ type: "USER", text });
    await stream("/api/sessions/" + current.current.chat.id + "/turn", {
      text,
      files,
      mode,
    });
  };
  const resume = () => {
    navigate("chat-view");
    return stream("/api/sessions/" + current.current.chat.id + "/resume");
  };
  const reset = async () => {
    if (
      !window.confirm(
        "Reset this conversation? Saved records and files remain available.",
      )
    )
      return;
    const id = current.current.chat.id;
    await json("/api/sessions/" + id + "/reset", { method: "POST" });
    await openSession(id);
  };
  const approve = (item, approved) =>
    perform(() =>
      stream(
        "/api/sessions/" + current.current.chat.id + "/approvals/" + item.id,
        { approved },
        { item, approved },
      ),
    );
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
    status("Settings saved.");
  };
  const openDialog = (kind, section = "") => {
    if (
      streamLock.current ||
      current.current.working ||
      !current.current.chat.id
    )
      return;
    if (current.current.mobile) setSidebarOpen(false);
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
      setSidebarOpen(!media.matches);
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
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    if (!me) return;
    const timer = setInterval(
      () =>
        json("/api/notifications")
          .then((items) => setNotifications(items.slice(0, 3)))
          .catch(() => {}),
      15000,
    );
    return () => clearInterval(timer);
  }, [json, me]);
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
    setSigningIn(true);
    try {
      await login();
      setOnboarding(null);
    } catch (error) {
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
        usage,
        working,
        setWorking,
        busy: chat.busy || working,
        view,
        navigate,
        dialog,
        openDialog,
        closeDialog,
        mobile,
        sidebarOpen,
        setSidebarOpen,
        theme,
        brand:
          theme === "light" ? "/static/brand-light.png" : "/static/brand.png",
        toggleTheme,
        draftRequest,
        editDraft,
        notifications,
        autoPlay,
        api,
        json,
        perform,
        status,
        showError,
        connections,
        refreshConnections,
        syncUsage,
        openSession,
        newSession,
        send,
        resume,
        reset,
        approve,
        patchSettings,
        runCommand,
        loginError,
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
