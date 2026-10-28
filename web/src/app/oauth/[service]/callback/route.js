import { forwardToBackend } from "../../../../server/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request, { params }) {
  const { service } = await params;
  if (!["gmail", "health", "zepto", "slack", "github"].includes(service))
    return new Response("Unknown account service.", { status: 404 });
  return forwardToBackend(request, `/oauth/${service}/callback`);
}
