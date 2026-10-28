import Workspace from "../components/Workspace";

export const dynamic = "force-dynamic";

export default function Home() {
  return <Workspace agentName={process.env.AGENT_NAME || "Theos"} />;
}
