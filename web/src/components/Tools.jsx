export default function Tools({ agentName }) {
  return (
    <>
      <section
        id="tools-view"
        className="workspace-panel"
        hidden
        aria-labelledby="tools-title"
      >
        <div className="panel-heading">
          <h1 id="tools-title">Conversation tools</h1>
          <button id="back-tools">← Back to chat</button>
        </div>
        <p>
          Tools available in this conversation. Expand a tool to inspect its
          inputs.
        </p>
        <label htmlFor="tool-search" className="sr-only">
          Search tools
        </label>
        <input id="tool-search" type="search" placeholder="Search tools…" />
        <p id="tool-count" role="status"></p>
        <div id="tools-content"></div>
      </section>
    </>
  );
}
