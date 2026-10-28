import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { accountDescriptions } from "../state/config";
import {
  closeSignIn,
  continueSignIn,
  prepareSignIn,
  signInUrl,
} from "../state/authorization";
import { ConnectionIcon, Glass, Icon } from "./Primitives";
import PanelHeading from "./PanelHeading";
import BrowserSignIn from "./BrowserSignIn";
import GitHubNotifications from "./GitHubNotifications";

function SignInLink({ url }) {
  try {
    return (
      <a
        href={signInUrl(url)}
        className="connection-link"
        target="_blank"
        rel="noopener noreferrer"
      >
        Open sign-in <Icon name="arrowUpRight" className="link-arrow" />
      </a>
    );
  } catch (error) {
    return <p className="error">{error.message}</p>;
  }
}

function AccountCard({ account, busy, action }) {
  const { json, editDraft } = useWorkspace();
  const [returnUrl, setReturnUrl] = useState("");
  const [authorizationUrl, setAuthorizationUrl] = useState("");
  const [notice, setNotice] = useState("");
  const popup = useRef(null),
    launchedUrl = useRef(""),
    starting = useRef(false);
  const setup = account.setup;
  const pending = ["starting", "waiting"].includes(setup.status);
  const failed = ["failed", "expired"].includes(setup.status);
  const url = setup.url || authorizationUrl;
  useEffect(() => {
    if (pending) starting.current = false;
    if (pending && url && launchedUrl.current !== url) {
      try {
        if (!continueSignIn(popup.current, url))
          setNotice("If sign-in did not open, select Open sign-in below.");
        launchedUrl.current = url;
      } catch (error) {
        setNotice(error.message);
        closeSignIn(popup.current);
      }
    }
    if (!pending && account.connected && !failed && !starting.current) {
      closeSignIn(popup.current);
      popup.current = null;
      setAuthorizationUrl("");
      setNotice("");
    }
    if (!pending && failed && !launchedUrl.current) closeSignIn(popup.current);
  }, [pending, url, account.connected, failed]);
  useEffect(() => () => closeSignIn(popup.current), []);
  const connect = () => {
    if (pending && popup.current && !popup.current.closed) {
      popup.current.focus();
      return;
    }
    popup.current = prepareSignIn(account.id);
    starting.current = true;
    launchedUrl.current = "";
    setNotice(
      popup.current
        ? "Opening private sign-in…"
        : "Allow popups or select Open sign-in when the link is ready.",
    );
    if (pending && url) {
      try {
        continueSignIn(popup.current, url);
        launchedUrl.current = url;
      } catch (error) {
        setNotice(error.message);
        closeSignIn(popup.current);
      }
      return;
    }
    setAuthorizationUrl("");
    action(async () => {
      try {
        const result = await json(`/api/connections/${account.id}/connect`, {
          method: "POST",
        });
        if (!["starting", "waiting"].includes(result.status))
          starting.current = false;
        if (result.url) setAuthorizationUrl(result.url);
      } catch (error) {
        starting.current = false;
        closeSignIn(popup.current);
        throw error;
      }
    });
  };
  return (
    <Glass
      as="article"
      className="connection-card liquid-panel"
      data-account={account.id}
    >
      <div className="connection-heading">
        <div className="connection-identity">
          <ConnectionIcon id={account.id} />
          <h3>{account.name}</h3>
        </div>
        <span
          className={
            "status-pill " +
            (pending
              ? "is-pending"
              : account.connected
                ? "is-connected"
                : "is-unavailable")
          }
        >
          {!account.configured
            ? "Not configured"
            : pending
              ? "Awaiting sign-in"
              : failed
                ? "Needs attention"
                : account.connected
                  ? "Connected"
                  : "Not connected"}
        </span>
      </div>
      <p>{accountDescriptions[account.id]}</p>
      {setup.message && (
        <p role="status" className={failed ? "error" : ""}>
          {setup.message}
        </p>
      )}
      {notice && pending && (
        <p className="connection-notice" role="status">
          {notice}
        </p>
      )}
      <div className="connection-actions">
        {account.configured && (
          <button
            className={account.connected ? "soft-button" : "primary"}
            disabled={busy || setup.status === "starting"}
            onClick={connect}
          >
            {setup.status === "starting"
              ? "Preparing sign-in…"
              : pending && url
                ? "Continue sign-in"
                : failed
                  ? "Try again"
                  : pending
                    ? "Start again"
                    : account.connected
                      ? "Reconnect"
                      : "Connect"}
          </button>
        )}
        {pending && (
          <button
            className="soft-button"
            disabled={busy}
            onClick={() =>
              action(async () => {
                await json(`/api/connections/${account.id}/cancel`, {
                  method: "POST",
                });
                closeSignIn(popup.current);
                setAuthorizationUrl("");
                setNotice("");
              })
            }
          >
            Cancel setup
          </button>
        )}
        {account.connected && !pending && (
          <button
            className="soft-button"
            disabled={busy}
            onClick={() => {
              if (
                window.confirm(
                  `Disconnect ${account.name} from your workspace?`,
                )
              )
                action(() =>
                  json(`/api/connections/${account.id}/disconnect`, {
                    method: "POST",
                  }),
                );
            }}
          >
            Disconnect
          </button>
        )}
        {pending && url && <SignInLink url={url} />}
      </div>
      {pending && setup.manual_return && (
        <details className="connection-handoff" open>
          <summary>Finish Zepto sign-in</summary>
          <p>
            After sign-in, your browser may show a localhost connection error.
            Copy the full link from its address bar and paste it here.
          </p>
          <form
            className="connection-return"
            onSubmit={(event) => {
              event.preventDefault();
              const value = returnUrl.trim();
              action(async () => {
                await json("/api/connections/zepto/finish", {
                  method: "POST",
                  body: { url: value },
                });
                setReturnUrl("");
                setNotice("Return link accepted. Checking the connection…");
              });
            }}
          >
            <label htmlFor="zepto-return-url">Return link</label>
            <input
              id="zepto-return-url"
              type="url"
              required
              maxLength={4000}
              autoComplete="off"
              placeholder="http://localhost/callback?…"
              value={returnUrl}
              onChange={(event) => setReturnUrl(event.target.value)}
              disabled={busy}
            />
            <button type="submit" disabled={busy || !returnUrl.trim()}>
              Finish connection
            </button>
          </form>
          <p>
            This private link goes to account setup. It is not sent to the chat.
          </p>
        </details>
      )}
      {account.id === "github" && account.connected && !pending && (
        <GitHubNotifications
          settings={account.notifications}
          busy={busy}
          action={action}
        />
      )}
      {account.id === "zepto" && account.connected && !pending && (
        <button
          className="soft-button connection-next"
          onClick={() =>
            editDraft(
              "Help me choose a saved Zepto delivery address before shopping.",
            )
          }
        >
          Choose a delivery address{" "}
          <Icon name="arrowUpRight" className="link-arrow" />
        </button>
      )}
    </Glass>
  );
}

function SetupProfile({ setup, busy, action }) {
  const { finishConnectionSetup } = useWorkspace();
  const [name, setName] = useState(setup.display_name || "");
  const [timezone, setTimezone] = useState(setup.timezone || "UTC");
  return (
    <Glass className="connection-onboarding">
      <span className="eyebrow">Make Theos yours</span>
      <h2>
        {setup.display_name
          ? `Welcome, ${setup.display_name}`
          : "What should I call you?"}
      </h2>
      <p>
        Choose the accounts you want to connect below. Every connection is
        optional.
      </p>
      <form
        id="connection-setup"
        onSubmit={(event) => {
          event.preventDefault();
          action(() =>
            finishConnectionSetup(
              setup.display_name ? {} : { display_name: name, timezone },
            ),
          );
        }}
      >
        {!setup.display_name && (
          <div className="connection-profile-fields">
            <label htmlFor="setup-name">
              Your preferred name
              <input
                id="setup-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={200}
                autoComplete="nickname"
                disabled={busy}
              />
            </label>
            <label htmlFor="setup-timezone">
              Timezone
              <input
                id="setup-timezone"
                value={timezone}
                onChange={(event) => setTimezone(event.target.value)}
                required
                maxLength={100}
                disabled={busy}
              />
            </label>
          </div>
        )}
      </form>
    </Glass>
  );
}

export default function Connections() {
  const {
    me,
    view,
    navigate,
    connections,
    refreshConnections,
    finishConnectionSetup,
  } = useWorkspace();
  const [status, setStatus] = useState(""),
    [error, setError] = useState(false),
    [busy, setBusy] = useState(false);
  const operation = useRef(false),
    generation = useRef(0);
  useEffect(() => {
    if (!me || view !== "connections-view") return;
    const id = ++generation.current;
    setStatus("Loading connections…");
    setError(false);
    const refresh = async () => {
      try {
        await refreshConnections();
        if (generation.current === id && !operation.current) setStatus("");
      } catch (error) {
        if (generation.current === id && error.name !== "AbortError") {
          setStatus(error.message);
          setError(true);
        }
      }
    };
    refresh();
    const timer = setInterval(() => {
      if (!operation.current) refresh();
    }, 1500);
    return () => {
      generation.current++;
      clearInterval(timer);
    };
  }, [view, me?.id, refreshConnections]);
  const action = async (callback) => {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError(false);
    setStatus("Updating connection…");
    try {
      await callback();
      await refreshConnections();
      setStatus("");
    } catch (error) {
      if (error.name !== "AbortError") {
        setError(true);
        setStatus(error.message);
      }
    } finally {
      operation.current = false;
      setBusy(false);
    }
  };
  const setup = connections?.onboarding;
  return (
    <section
      id="connections-view"
      className="workspace-panel"
      hidden={view !== "connections-view"}
      aria-labelledby="connections-title"
    >
      <PanelHeading active={view === "connections-view"}>
        <div>
          <span className="eyebrow">Your workspace</span>
          <h1 id="connections-title">Connections</h1>
          <div className="panel-header-subtext">
            <span className="cost-label">
              Connect your accounts and services.
            </span>
          </div>
        </div>
        <button
          id="back-connections"
          className="panel-back"
          aria-label="Back to chat"
          title="Back to chat"
          onClick={() => navigate("chat-view")}
        >
          <Icon name="back" />
          <span>Back to chat</span>
        </button>
      </PanelHeading>
      {setup?.needed ? (
        <SetupProfile key={me?.id} setup={setup} busy={busy} action={action} />
      ) : (
        <p className="panel-description">
          Connect your own accounts. Connections and personal records are
          available across your private conversations.
        </p>
      )}
      <div className="connection-heading">
        <div className="section-title">
          <h2>Your accounts</h2>
          <span id="connection-summary">
            {connections
              ? `${connections.accounts.filter((account) => account.connected).length} connected · ${connections.accounts.length} accounts`
              : ""}
          </span>
        </div>
        <button
          id="refresh-connections"
          className="soft-button"
          disabled={busy}
          aria-busy={busy ? true : undefined}
          onClick={() => action(async () => {})}
        >
          <Icon name="refresh" />
          Refresh
        </button>
      </div>
      <p
        id="connections-status"
        role="status"
        aria-live="polite"
        className={error ? "error" : ""}
      >
        {status}
      </p>
      <div id="account-connections">
        {connections?.accounts.map((account) => (
          <AccountCard
            key={`${me?.id}:${account.id}`}
            account={account}
            busy={busy}
            action={action}
          />
        ))}
      </div>
      {setup?.needed && (
        <div className="connection-setup-actions">
          <button
            className="primary"
            type="submit"
            form="connection-setup"
            disabled={busy}
          >
            Continue to chat
          </button>
          <button
            className="soft-button"
            disabled={busy}
            onClick={() => action(() => finishConnectionSetup())}
          >
            Skip for now
          </button>
        </div>
      )}
      <BrowserSignIn
        key={me?.id}
        configured={connections?.services.some(
          (service) => service.id === "sandbox" && service.configured,
        )}
      />
      <h2 className="connection-heading">Workspace services</h2>
      <p>
        Configured by the operator. These labels show availability, not a live
        service check. Each conversation uses its own sandbox.
      </p>
      <Glass className="services-panel liquid-panel">
        {connections?.services.map((service) => (
          <div className="service-row" key={service.id}>
            <div className="connection-identity">
              <ConnectionIcon id={service.id} />
              <strong>{service.name}</strong>
            </div>
            <span
              className={`status-pill ${service.configured ? "is-connected" : "is-unavailable"}`}
            >
              {service.configured ? "Configured" : "Not configured"}
            </span>
          </div>
        ))}
      </Glass>
    </section>
  );
}
