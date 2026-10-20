export default function Dialogs({ agentName }) {
  return (
    <>
      <dialog id="generation-dialog" aria-labelledby="generation-title">
        <form id="generation-form">
          <div className="dialog-heading">
            <div>
              <span className="eyebrow">Conversation</span>
              <h2 id="generation-title">Settings</h2>
            </div>
            <button
              id="generation-close"
              className="icon-button"
              type="button"
              aria-label="Close settings"
            ></button>
          </div>
          <p id="settings-conversation"></p>
          <div className="settings-model-fields">
            <div className="generation-field">
              <label htmlFor="model">Model</label>
              <select id="model" aria-describedby="model-hint"></select>
              <small id="model-hint">
                Choose a model for this conversation.
              </small>
            </div>
            <div className="generation-field">
              <label htmlFor="reasoning">Reasoning effort</label>
              <select id="reasoning" aria-describedby="reasoning-hint"></select>
              <small id="reasoning-hint">
                Options depend on the selected model.
              </small>
            </div>
          </div>
          <details id="generation-options" className="settings-section">
            <summary>Generation parameters</summary>
            <p id="generation-model"></p>
            <p>Leave a value empty to use the model's default.</p>
            <div id="generation-fields" className="generation-fields"></div>
            <button id="generation-defaults" type="button">
              Use parameter defaults
            </button>
          </details>
          <fieldset className="voice-settings">
            <legend>Voice</legend>
            <p id="voice-services"></p>
            <label>
              <input id="auto-speech" type="checkbox" /> Read new replies aloud
            </label>
            <small>
              Microphone recordings become editable text. Use the speaker button
              for speech playback.
            </small>
          </fieldset>
          <p id="generation-error" className="error" role="alert"></p>
          <div className="dialog-actions">
            <button id="generation-cancel" type="button">
              Cancel
            </button>
            <button className="primary" type="submit">
              Save settings
            </button>
          </div>
        </form>
      </dialog>
      <dialog id="research-dialog" aria-labelledby="research-title">
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">Saved evidence</span>
            <h2 id="research-title">Research</h2>
          </div>
          <button id="research-close" type="button" aria-label="Close research">
            Close
          </button>
        </div>
        <p id="research-status" role="status"></p>
        <div id="research-runs" className="research-runs"></div>
        <div id="research-detail" className="research-detail"></div>
        <div className="dialog-actions">
          <button id="research-refresh" type="button">
            Refresh
          </button>
        </div>
      </dialog>
      <dialog id="usage-dialog" aria-labelledby="usage-title">
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">Your workspace</span>
            <h2 id="usage-title">Usage</h2>
          </div>
          <button
            id="usage-close"
            className="icon-button"
            type="button"
            aria-label="Close usage"
          ></button>
        </div>
        <p id="usage-status" role="status"></p>
        <div id="usage-content" className="usage-grid"></div>
        <p className="usage-note">
          Costs use reported amounts or configured USD estimates. Requests
          without a recorded price remain visible.
        </p>
        <div className="dialog-actions">
          <button id="usage-refresh" type="button">
            Refresh usage
          </button>
        </div>
      </dialog>
      <dialog id="help-dialog" aria-labelledby="help-title">
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">Shortcuts</span>
            <h2 id="help-title">Commands</h2>
          </div>
          <button
            id="help-close"
            className="icon-button"
            type="button"
            aria-label="Close command help"
          ></button>
        </div>
        <p>Choose a command. Commands with options show a selection menu.</p>
        <div id="help-commands" className="help-commands"></div>
        <p className="keyboard-hint">
          Type / for commands or @ for connections. ↑ ↓ to select · Enter or Tab
          to choose · Escape to close.
          <br />
          Enter to send · Shift + Enter for a new line.
        </p>
      </dialog>
    </>
  );
}
