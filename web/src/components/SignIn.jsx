export default function SignIn({ agentName }) {
  return (
    <>
      <div id="login" className="login-wrap">
        <form id="login-form" className="login-card">
          <img
            src="/static/brand.png"
            data-brand=""
            width="48"
            height="48"
            alt=""
          />
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
          />
          <button className="primary" type="submit">
            Open workspace <span aria-hidden="true">↗</span>
          </button>
          <p id="login-error" className="error" role="alert"></p>
          <small>Your browser uses a protected session after sign-in.</small>
        </form>
        <section
          id="web-signin"
          className="login-card"
          aria-labelledby="web-signin-title"
          hidden
        >
          <img
            src="/static/brand.png"
            data-brand=""
            width="48"
            height="48"
            alt=""
          />
          <span className="eyebrow">Your Theos account</span>
          <h1 id="web-signin-title">Confirm in Telegram</h1>
          <p id="web-signin-instructions">
            Match this code with the message in your private bot chat, then
            select Approve browser.
          </p>
          <output
            id="web-signin-code"
            className="signin-code"
            aria-label="Browser confirmation code"
          ></output>
          <p id="web-signin-status" role="status" aria-live="polite">
            Preparing your sign-in…
          </p>
          <div id="web-token-save" hidden>
            <label htmlFor="web-access-token">Your personal access token</label>
            <input
              id="web-access-token"
              type="password"
              readOnly
              autoComplete="off"
              spellCheck="false"
            />
            <button id="copy-web-token" type="button">
              Copy access token
            </button>
            <small>
              Save this token privately to sign in on another device. A new
              Telegram sign-in replaces your previous saved token.
            </small>
            <button id="finish-web-signin" className="primary" type="button">
              Open workspace ↗
            </button>
          </div>
          <button id="cancel-web-signin" type="button">
            Back to token sign-in
          </button>
        </section>
      </div>
    </>
  );
}
