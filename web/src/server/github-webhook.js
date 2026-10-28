import "server-only";
import { fetch as upstreamFetch } from "undici";

const limit = 1024 * 1024;

export async function forwardGitHubWebhook(request) {
  const base = new URL(process.env.THEOS_API_URL || "http://127.0.0.1:8080");
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.pathname !== "/"
  )
    throw new Error("THEOS_API_URL must be an HTTP or HTTPS origin.");
  const parts = [];
  let size = 0;
  const reader = request.body?.getReader();
  if (reader) {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > limit) {
          await reader.cancel();
          return Response.json(
            { detail: "The GitHub webhook payload is too large." },
            { status: 413 },
          );
        }
        parts.push(value);
      }
    } finally {
      reader.releaseLock();
    }
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    body.set(part, offset);
    offset += part.byteLength;
  }
  const headers = new Headers();
  for (const name of [
    "content-type",
    "x-hub-signature-256",
    "x-github-delivery",
    "x-github-event",
  ])
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  // This public endpoint authenticates the signed bytes. Never forward browser credentials.
  const url = new URL("/webhooks/github", base);
  let result;
  try {
    result = await upstreamFetch(url, {
      method: "POST",
      headers,
      body,
      redirect: "manual",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(10000)]),
    });
  } catch {
    return Response.json(
      { detail: "The webhook service is unavailable. Redeliver later." },
      { status: 502 },
    );
  }
  return new Response(result.body, {
    status: result.status,
    headers: {
      "Content-Type": result.headers.get("content-type") || "application/json",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}
