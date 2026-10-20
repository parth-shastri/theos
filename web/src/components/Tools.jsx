import { useEffect, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";
import { Icon } from "./Primitives";
import PanelHeading from "./PanelHeading";
export default function Tools() {
  const { view, chat, navigate, json, showError, mobile } = useWorkspace();
  const [catalog, setCatalog] = useState([]),
    [query, setQuery] = useState("");
  useEffect(() => {
    if (view !== "tools-view" || !chat.id) return;
    const controller = new AbortController();
    setQuery("");
    json("/api/sessions/" + chat.id + "/tools", { signal: controller.signal })
      .then(setCatalog)
      .catch((error) => {
        if (!controller.signal.aborted) showError(error);
      });
    return () => controller.abort();
  }, [view, chat.id, json, showError]);
  const tools = catalog.filter((tool) =>
    (tool.name + " " + tool.description)
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <section
      id="tools-view"
      className="workspace-panel"
      hidden={view !== "tools-view"}
      aria-labelledby="tools-title"
    >
      <PanelHeading active={view === "tools-view"}>
        <div>
          <span className="eyebrow">Your workspace</span>
          <h1 id="tools-title">{mobile ? "Conversation tools" : "Tools"}</h1>
          <div className="panel-header-subtext">
            <span className="cost-label">
              Tools available in this conversation.
            </span>
          </div>
        </div>
        <button
          id="back-tools"
          className="panel-back"
          aria-label="Back to chat"
          title="Back to chat"
          onClick={() => navigate("chat-view")}
        >
          <Icon name="back" />
          <span>Back to chat</span>
        </button>
      </PanelHeading>
      <p>
        Tools available in this conversation. Expand a tool to inspect its
        inputs.
      </p>
      <label htmlFor="tool-search" className="sr-only">
        Search tools
      </label>
      <input
        id="tool-search"
        type="search"
        placeholder="Search tools…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <p id="tool-count" role="status">
        {tools.length + " of " + catalog.length + " tools"}
      </p>
      <div id="tools-content">
        {!tools.length && <p>No matching tools.</p>}
        {tools.map((tool) => (
          <details className="tool-card" key={tool.name}>
            <summary>
              <strong>{tool.name}</strong>
              <span
                className={
                  tool.requires_approval ? "approval-badge" : "tool-badge"
                }
              >
                {tool.requires_approval ? "Approval required" : "Available"}
              </span>
            </summary>
            <p>{tool.description}</p>
            <strong>Inputs</strong>
            <pre>{JSON.stringify(tool.parameters, null, 2)}</pre>
          </details>
        ))}
      </div>
    </section>
  );
}
