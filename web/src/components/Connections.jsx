import { useCallback, useEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { accountDescriptions } from "../state/config";
import { ConnectionIcon, Glass, Icon } from "./Primitives";
import PanelHeading from "./PanelHeading";
function SignInLink({ url }) {
  try {
    const parsed = new URL(url);
    if (
      !["https:", "http:"].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password
    )
      throw new Error("The service returned an invalid sign-in link.");
    if (
      parsed.protocol === "http:" &&
      !["localhost", "127.0.0.1"].includes(parsed.hostname)
    )
      throw new Error("The sign-in link must use HTTPS.");
    return (
      <a
        href={parsed.href}
        className="connection-link"
        target="_blank"
        rel="noopener noreferrer"
      >
        Continue sign-in ↗
      </a>
    );
  } catch (error) {
    return <p className="error">{error.message}</p>;
  }
}
function AccountCard({ account, busy, action, authorizationUrl, rememberUrl }) {
  const { json } = useWorkspace();
  const [returnUrl, setReturnUrl] = useState("");
  const setup = account.setup,
    pending = ["starting", "waiting"].includes(setup.status);
  return (
    <Glass as="article" className="connection-card liquid-panel">
      <div className="connection-heading">
        <div className="connection-identity">
          <ConnectionIcon id={account.id} />
          <h3>{account.name}</h3>
        </div>
        <span
          className={
            "status-pill " +
            (account.connected
              ? "is-connected"
              : pending
                ? "is-pending"
                : "is-unavailable")
          }
        >
          {!account.configured
            ? "Not configured"
            : pending
              ? "Awaiting sign-in"
              : account.connected
                ? "Connected"
                : "Not connected"}
        </span>
      </div>
      <p>{accountDescriptions[account.id]}</p>
      {setup.message && (
        <p className={setup.status === "failed" ? "error" : ""}>
          {setup.message}
        </p>
      )}
      <div className="connection-actions">
        {account.configured && (
          <button
            className={account.connected ? "soft-button" : "primary"}
            disabled={busy || setup.status === "starting"}
            onClick={() =>
              action(async () => {
                const result = await json(
                  "/api/connections/" + account.id + "/connect",
                  { method: "POST" },
                );
                if (result.url) rememberUrl(account.id, result.url);
              })
            }
          >
            {pending
              ? account.id === "zepto"
                ? "Continue setup"
                : "Start again"
              : account.connected
                ? "Reconnect"
                : "Connect"}
          </button>
        )}
        {(account.connected || pending) && (
          <button
            className="soft-button"
            disabled={busy}
            onClick={() => {
              if (
                account.connected &&
                !window.confirm(
                  "Disconnect " + account.name + " from your workspace?",
                )
              )
                return;
              action(async () => {
                await json("/api/connections/" + account.id + "/disconnect", {
                  method: "POST",
                });
                rememberUrl(account.id, null);
              });
            }}
          >
            {account.connected ? "Disconnect" : "Cancel setup"}
          </button>
        )}
        {pending && (setup.url || authorizationUrl) && (
          <SignInLink url={setup.url || authorizationUrl} />
        )}
      </div>
      {pending && setup.manual_return && (
        <form
          className="connection-return"
          onSubmit={(event) => {
            event.preventDefault();
            const url = returnUrl.trim();
            setReturnUrl("");
            event.currentTarget.querySelector("input").blur();
            action(() =>
              json("/api/connections/zepto/finish", {
                method: "POST",
                body: { url },
              }),
            );
          }}
        >
          <label htmlFor="zepto-return-url">
            After sign-in, paste the full localhost return URL here.
          </label>
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
          <button type="submit" disabled={busy}>
            Finish connection
          </button>
        </form>
      )}
    </Glass>
  );
}
export default function Connections() {
  const { view, navigate, connections, refreshConnections } = useWorkspace();
  const [status, setStatus] = useState(""),
    [error, setError] = useState(false),
    [busy, setBusy] = useState(false),
    [links, setLinks] = useState({});
  const operation = useRef(false),
    generation = useRef(0);
  useEffect(() => {
    if (view !== "connections-view") return;
    const id = ++generation.current;
    setStatus("Loading connections…");
    setError(false);
    const refresh = async () => {
      try {
        await refreshConnections();
        if (generation.current === id) {
          setStatus("Account status refreshes while this view is open.");
          setError(false);
        }
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
    }, 3000);
    return () => {
      generation.current++;
      clearInterval(timer);
    };
  }, [view, refreshConnections]);
  const action = async (callback) => {
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError(false);
    setStatus("Updating connection…");
    try {
      await callback();
      await refreshConnections();
      setStatus("Connection status updated.");
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
      <p className="panel-description">
        Connect your own accounts. Connections and personal records are
        available across your private conversations.
      </p>
      <div className="connection-heading">
        <div className="section-title">
          <h2>Your accounts</h2>
          <span id="connection-summary">
            {connections
              ? connections.accounts.filter((account) => account.connected)
                  .length +
                " connected · " +
                connections.accounts.length +
                " accounts"
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
            key={account.id}
            account={account}
            busy={busy}
            action={action}
            authorizationUrl={links[account.id]}
            rememberUrl={(id, url) =>
              setLinks((links) => ({ ...links, [id]: url }))
            }
          />
        ))}
      </div>
      <h2 className="connection-heading">Workspace services</h2>
      <p>
        Configured by the operator. These labels show availability, not a live
        service check. Each conversation uses its own sandbox.
      </p>
      <Glass className="services-panel liquid-panel">
        <div id="workspace-services" className="service-grid">
          {connections?.services.map((service) => (
            <div className="service-row" key={service.id}>
              <div className="connection-identity">
                <ConnectionIcon id={service.id} />
                <strong>{service.name}</strong>
              </div>
              <span
                className={
                  "status-pill " +
                  (service.configured ? "is-connected" : "is-unavailable")
                }
              >
                {service.configured ? "Configured" : "Not configured"}
              </span>
            </div>
          ))}
        </div>
      </Glass>
    </section>
  );
}
