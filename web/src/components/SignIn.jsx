import { useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";
export default function SignIn() {
  const {
    agentName,
    me,
    brand,
    loginError,
    signingIn,
    signIn,
    onboarding,
    finishSignin,
    cancelSignin,
  } = useWorkspace();
  const [token, setToken] = useState(""),
    [copy, setCopy] = useState("Copy access token"),
    [showToken, setShowToken] = useState(false);
  const accessToken = useRef(null);
  return (
    <div id="login" className="login-wrap" hidden={!!me}>
      <form
        id="login-form"
        className="login-card"
        hidden={!!onboarding}
        onSubmit={async (event) => {
          event.preventDefault();
          const value = token;
          setToken("");
          await signIn(value);
        }}
      >
        <img src={brand} data-brand="" width="48" height="48" alt="" />
        <h1 id="agent-name">{agentName}</h1>
        <p>
          Your personal assistant for conversations, saved information, and
          everyday tasks.
        </p>
        <label htmlFor="token">Access token</label>
        <input
          id="token"
          type="password"
          autoComplete="current-password"
          placeholder="Enter your browser token"
          required
          value={token}
          onChange={(event) => setToken(event.target.value)}
        />
        <button className="primary" type="submit" disabled={signingIn}>
          Open workspace <Icon name="arrowUpRight" className="link-arrow" />
        </button>
        <p id="login-error" className="error" role="alert">
          {loginError}
        </p>
        <small>Your browser uses a protected session after sign-in.</small>
      </form>
      <section
        id="web-signin"
        className="login-card"
        aria-labelledby="web-signin-title"
        hidden={!onboarding}
      >
        <img src={brand} data-brand="" width="48" height="48" alt="" />
        <span className="eyebrow">Your Theos account</span>
        <h1 id="web-signin-title">
          {onboarding?.token ? "Your account is ready" : "Confirm in Telegram"}
        </h1>
        <p id="web-signin-instructions">
          {onboarding?.token
            ? "Save your personal access token, then open your workspace."
            : "Match this code with the message in your private bot chat, then select Approve browser."}
        </p>
        <output
          id="web-signin-code"
          className="signin-code"
          aria-label="Browser confirmation code"
          hidden={!!onboarding?.token}
        >
          {onboarding?.code}
        </output>
        <p
          id="web-signin-status"
          role="status"
          aria-live="polite"
          className={onboarding?.error ? "error" : ""}
        >
          {onboarding?.error || onboarding?.status || "Preparing your sign-in…"}
        </p>
        <div id="web-token-save" hidden={!onboarding?.token}>
          <label htmlFor="web-access-token">Your personal access token</label>
          <input
            id="web-access-token"
            type={showToken ? "text" : "password"}
            readOnly
            autoComplete="off"
            spellCheck={false}
            value={onboarding?.token || ""}
            ref={accessToken}
          />
          <button
            id="copy-web-token"
            type="button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(onboarding.token);
                setCopy("Copied");
              } catch {
                setShowToken(true);
                requestAnimationFrame(() => accessToken.current.select());
                setCopy("Select and copy the token");
              }
            }}
          >
            {copy}
          </button>
          <small>
            Save this token privately to sign in on another device. A new
            Telegram sign-in replaces your previous saved token.
          </small>
          <button
            id="finish-web-signin"
            className="primary"
            type="button"
            disabled={signingIn}
            onClick={finishSignin}
          >
            Open workspace <Icon name="arrowUpRight" className="link-arrow" />
          </button>
        </div>
        <button
          id="cancel-web-signin"
          type="button"
          hidden={!!onboarding?.token}
          onClick={cancelSignin}
        >
          Back to token sign-in
        </button>
      </section>
    </div>
  );
}
