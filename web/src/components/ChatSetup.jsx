"use client";

import { useEffect, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { AccountCard } from "./Connections";
import CallSetup from "./CallSetup";
import { Glass, Icon } from "./Primitives";

export default function ChatSetup() {
  const {
    me,
    journey,
    journeyWorking,
    journeyError,
    advanceJourney,
    perform,
    editDraft,
  } = useWorkspace();
  if (!me || !journey || (!journey.needed && !journey.pending_task))
    return null;
  const step = journey.step;
  const act = (action, value) => perform(() => advanceJourney(action, value));
  const suggestedZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const confirming = step.startsWith("confirm_");
  const question =
    step === "ready"
      ? "Ready to continue your request?"
      : step === "name"
        ? "What should I call you?"
        : step === "confirm_name"
          ? `Shall I call you ${journey.candidate}?`
          : step === "confirm_timezone"
            ? `Use ${journey.candidate} for reminders?`
            : "Which timezone should I use?";
  return (
    <Glass
      as="section"
      className="chat-setup"
      aria-labelledby="chat-setup-title"
      aria-busy={journeyWorking}
    >
      <div className="chat-setup-heading">
        <Icon name={step === "ready" ? "chat" : "settings"} />
        <span>Theos</span>
        <span className="cost-label">
          {step === "ready" ? "Your saved request" : "Let’s get acquainted"}
        </span>
      </div>
      <h2 id="chat-setup-title">{question}</h2>
      <p>
        {step === "ready"
          ? journey.pending_task
          : step === "name" || step === "confirm_name"
            ? "Reply below. You can change your name later or start chatting now."
            : "Send a city or timezone below. This helps me interpret local times. You can change it later."}
      </p>
      {journey.notice && <p role="status">{journey.notice}</p>}
      <div className="chat-setup-actions">
        {confirming && (
          <>
            <button
              className="primary"
              disabled={journeyWorking}
              onClick={() => act("confirm")}
            >
              Yes, save it
            </button>
            <button
              className="soft-button"
              disabled={journeyWorking}
              onClick={() => act("change")}
            >
              Change
            </button>
          </>
        )}
        {step === "name" && journey.display_name && (
          <button
            className="primary"
            disabled={journeyWorking}
            onClick={() => act("keep")}
          >
            Call me {journey.display_name}
          </button>
        )}
        {step === "timezone" && (
          <>
            <button
              className="primary"
              disabled={journeyWorking}
              onClick={() => act("reply", suggestedZone)}
            >
              Use {suggestedZone}
            </button>
            {journey.choices?.map((zone) => (
              <button
                className="soft-button"
                key={zone}
                disabled={journeyWorking}
                onClick={() => act("reply", zone)}
              >
                {zone}
              </button>
            ))}
          </>
        )}
        {step === "ready" ? (
          <button
            className="primary"
            disabled={journeyWorking}
            onClick={() =>
              perform(async () => {
                const task = journey.pending_task;
                await advanceJourney("consume");
                editDraft(task);
              })
            }
          >
            Continue my request
          </button>
        ) : (
          <>
            <button
              className="soft-button"
              disabled={journeyWorking}
              onClick={() => act("skip")}
            >
              Skip for now
            </button>
            <button
              className="soft-button"
              disabled={journeyWorking}
              onClick={() => act("finish")}
            >
              Start chatting
            </button>
          </>
        )}
      </div>
      <p className="error" role="alert">
        {journeyError}
      </p>
    </Glass>
  );
}

export function ChatAccountSetup() {
  const {
    me,
    chat,
    accountSetup,
    setAccountSetup,
    connections,
    refreshConnections,
  } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = !!me && accountSetup?.sessionId === chat.id;
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await refreshConnections();
      } catch (error) {
        if (!controller.signal.aborted && error.name !== "AbortError")
          setError(error.message);
      } finally {
        inFlight = false;
      }
    };
    void refresh();
    const timer = setInterval(refresh, 2000);
    window.addEventListener("focus", refresh);
    return () => {
      controller.abort();
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, [active, refreshConnections]);
  if (!active) return null;
  const account = connections?.accounts.find(
    (account) => account.id === accountSetup.service,
  );
  const action = async (callback) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await callback();
      await refreshConnections();
    } catch (error) {
      if (error.name !== "AbortError") setError(error.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="chat-account-setup" aria-label="Account setup in chat">
      {accountSetup.service === "calls" && connections?.calling?.configured ? (
        <CallSetup calling={connections?.calling} busy={busy} action={action} />
      ) : account ? (
        <AccountCard
          key={account.id}
          account={account}
          busy={busy}
          action={action}
          source="chat"
        />
      ) : (
        <p role="status">
          {connections
            ? "This account is unavailable on this deployment. You can keep chatting."
            : "Loading your account…"}
        </p>
      )}
      <p className="error" role="alert">
        {error}
      </p>
      <button
        className="soft-button"
        disabled={busy}
        onClick={() => setAccountSetup(null)}
      >
        {account?.connected ? "Continue chatting" : "Done"}
      </button>
    </section>
  );
}
