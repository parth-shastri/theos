export default function Conversation({ agentName }) {
  return (
    <>
      <div className="workspace-toolbar" id="conversation-toolbar">
        <div>
          <span className="eyebrow">Conversation</span>
          <h2 id="session-title">New conversation</h2>
          <span id="conversation-cost" className="cost-label"></span>
        </div>
        <details id="conversation-actions" className="conversation-actions">
          <summary
            aria-label="Conversation actions"
            title="Conversation actions"
          >
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <circle cx="5" cy="12" r="1.75" />
              <circle cx="12" cy="12" r="1.75" />
              <circle cx="19" cy="12" r="1.75" />
            </svg>
            <span className="conversation-actions-label">
              Conversation actions
            </span>
          </summary>
          <div className="conversation-menu">
            <button
              id="research-button"
              type="button"
              aria-haspopup="dialog"
              aria-controls="research-dialog"
            >
              Saved research
            </button>
            <button id="resume" type="button">
              Resume conversation
            </button>
            <button id="reset" type="button">
              Reset conversation
            </button>
          </div>
        </details>
      </div>
      <section id="chat-view" className="chat-view">
        <div id="notifications" aria-live="polite"></div>
        <div
          id="messages"
          role="log"
          aria-label="Conversation"
          tabIndex="0"
          aria-live="polite"
        ></div>
        <div className="composer-wrap">
          <div id="approvals"></div>
          <form id="composer">
            <div
              id="command-suggestions"
              className="command-suggestions"
              role="listbox"
              aria-label="Slash commands"
              hidden
            ></div>
            <label className="sr-only" htmlFor="message">
              Message
            </label>
            <div
              id="composer-options"
              className="composer-options"
              role="group"
              aria-label="Add files and options"
              hidden
            >
              <button
                id="attach-files"
                className="composer-option"
                type="button"
              >
                Attach files
              </button>
              <input id="upload" type="file" multiple hidden />
              <button
                id="command-help"
                className="composer-option"
                type="button"
              >
                Commands & connections
              </button>
              <button
                id="composer-settings"
                className="composer-option"
                type="button"
              >
                Conversation settings
              </button>
            </div>
            <div
              id="mode-menu"
              className="mode-menu"
              role="listbox"
              aria-label="Message mode"
              hidden
            >
              <button
                type="button"
                role="option"
                data-mode="normal"
                aria-selected="true"
                tabIndex="-1"
              ></button>
              <button
                type="button"
                role="option"
                data-mode="deep_research"
                aria-selected="false"
                tabIndex="-1"
              ></button>
            </div>
            <div className="composer-row">
              <div className="composer-tools">
                <button
                  id="composer-add"
                  className="icon-button composer-action"
                  type="button"
                  aria-label="Add files and options"
                  aria-expanded="false"
                  aria-controls="composer-options"
                ></button>
                <div className="research-controls composer-config">
                  <input
                    id="research-mode"
                    type="hidden"
                    defaultValue="normal"
                  />
                  <button
                    id="mode-trigger"
                    type="button"
                    aria-haspopup="listbox"
                    aria-expanded="false"
                    aria-controls="mode-menu"
                    aria-describedby="research-mode-hint"
                  ></button>
                  <small id="research-mode-hint" className="sr-only">
                    For this message only
                  </small>
                </div>
              </div>
              <textarea
                id="message"
                role="combobox"
                aria-autocomplete="list"
                aria-controls="command-suggestions"
                aria-expanded="false"
                aria-describedby="message-hint"
                placeholder="Sue the void"
                rows="1"
                maxLength="32000"
                required
              ></textarea>
              <div className="composer-actions">
                <button
                  id="microphone"
                  className="icon-button voice-button"
                  type="button"
                  aria-label="Record a voice message"
                  disabled
                ></button>
                <button
                  id="cancel-recording"
                  className="icon-button voice-button"
                  type="button"
                  aria-label="Cancel recording"
                  title="Cancel recording"
                  hidden
                ></button>
                <button
                  className="primary icon-button send"
                  id="send"
                  type="submit"
                  aria-label="Send message"
                  title="Send message"
                ></button>
              </div>
            </div>
            <p id="status" role="status" aria-atomic="true"></p>
            <div id="attachments"></div>
            <span id="message-hint" className="sr-only">
              Enter to send · Shift + Enter for a new line
            </span>
          </form>
          <small className="footnote">
            Review external actions before you approve them.
          </small>
        </div>
      </section>
    </>
  );
}
