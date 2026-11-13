import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";
import PasswordSettings from "./PasswordSettings";
export default function SignIn() {
  const {
    agentName,
    me,
    brand,
    loginError,
    clearLoginError,
    signingIn,
    signIn,
    onboarding,
    finishSignin,
    cancelSignin,
  } = useWorkspace();
  const [token, setToken] = useState(""),
    [copy, setCopy] = useState("Copy access token"),
    [showToken, setShowToken] = useState(false);
  const [passwordMode, setPasswordMode] = useState(false);
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [showPasswordSettings, setShowPasswordSettings] = useState(false);
  const accessToken = useRef(null);
  const ready = Boolean(onboarding?.account);
  useEffect(() => {
    if (!ready) setShowPasswordSettings(false);
  }, [ready]);
  return (
    <div id="login" className="login-wrap" hidden={!!me}>
      <form
        id="login-form"
        className="login-card"
        hidden={!!onboarding}
        method="post"
        onSubmit={async (event) => {
          event.preventDefault();
          const credentials = passwordMode
            ? { account, password }
            : { token: token.trim() };
          setToken("");
          setPassword("");
          await signIn(credentials);
        }}
      >
        <img src={brand} data-brand="" width="48" height="48" alt="" />
        <h1 id="agent-name">{agentName}</h1>
        <p>
          Your personal assistant for conversations, saved information, and
          everyday tasks.
        </p>
        {passwordMode ? (
          <>
            <label htmlFor="login-account">Account ID</label>
            <input
              id="login-account"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={account}
              onChange={(event) => setAccount(event.target.value)}
            />
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </>
        ) : (
          <>
            <label htmlFor="token">Access token</label>
            <input
              id="token"
              type="password"
              autoComplete="off"
              placeholder="Enter your browser token"
              required
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </>
        )}
        <button className="primary" type="submit" disabled={signingIn}>
          Open workspace <Icon name="arrowUpRight" className="link-arrow" />
        </button>
        <p id="login-error" className="error" role="alert">
          {loginError}
        </p>
        <button
          type="button"
          className="soft-button"
          disabled={signingIn}
          onClick={() => {
            setPasswordMode(!passwordMode);
            setToken("");
            setPassword("");
            clearLoginError();
          }}
        >
          {passwordMode ? "Use an access token" : "Use a password"}
        </button>
        {passwordMode && (
          <small>Telegram users can send /web for a new sign-in link.</small>
        )}
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
          {ready
            ? onboarding.token
              ? "Your account is ready"
              : "Browser password"
            : "Confirm in Telegram"}
        </h1>
        <p id="web-signin-instructions">
          {ready
            ? onboarding.token
              ? "Save your access token or set an optional password for future sign-ins."
              : "Set, change, or remove your optional password."
            : "Match this code with the message in your private bot chat, then select Approve browser."}
        </p>
        <output
          id="web-signin-code"
          className="signin-code"
          aria-label="Browser confirmation code"
          hidden={ready}
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
        </div>
        {ready && (
          <>
            {!onboarding.token || showPasswordSettings ? (
              <PasswordSettings
                key={onboarding.account}
                account={onboarding.account}
              />
            ) : (
              <button
                type="button"
                onClick={() => setShowPasswordSettings(true)}
              >
                Set an optional password
              </button>
            )}
            <button
              id="finish-web-signin"
              className="primary"
              type="button"
              disabled={signingIn}
              onClick={finishSignin}
            >
              Open workspace <Icon name="arrowUpRight" className="link-arrow" />
            </button>
          </>
        )}
        <button
          id="cancel-web-signin"
          type="button"
          hidden={ready}
          onClick={cancelSignin}
        >
          Back to sign-in
        </button>
      </section>
    </div>
  );
}
