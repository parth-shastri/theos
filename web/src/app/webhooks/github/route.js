import { forwardGitHubWebhook } from "../../../server/github-webhook";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request) {
  return forwardGitHubWebhook(request);
}
