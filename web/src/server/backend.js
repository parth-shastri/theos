import "server-only";
import { isIP } from "node:net";
import { Agent, fetch as upstreamFetch } from "undici";

// Model calls can remain silent for several minutes. Disconnects still abort the request.
const dispatcher = new Agent({ headersTimeout: 0, bodyTimeout: 0 });

const COOKIE_NAMES = new Set([
  "theos-session",
  "theos-pairing",
  "__Host-theos-session",
  "__Secure-theos-pairing",
]);

export async function forwardToBackend(request, path) {
  if (
    process.env.NODE_ENV === "production" &&
    (!process.env.AGENT_WEB_URL ||
      (process.env.THEOS_FRONTEND_SECRET || "").length < 32)
  )
    return Response.json(
      { detail: "The frontend service is not configured." },
      { status: 503 },
    );
  const origin = process.env.AGENT_WEB_URL || new URL(request.url).origin;
  if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
    if (
      request.headers.get("origin") !== origin ||
      request.headers.get("x-theos-request") !== "1"
    )
      return Response.json(
        { detail: "Use the web UI on this deployment to continue." },
        { status: 403 },
      );
  }
  const base = new URL(process.env.THEOS_API_URL || "http://127.0.0.1:8080");
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.pathname !== "/"
  )
    throw new Error("THEOS_API_URL must be an HTTP or HTTPS origin.");
  const headers = new Headers();
  for (const name of ["accept", "content-type", "x-theos-request", "origin"])
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  const cookies = (request.headers.get("cookie") || "")
    .split(";")
    .filter((cookie) => COOKIE_NAMES.has(cookie.trim().split("=", 1)[0]))
    .join(";");
  if (cookies) headers.set("cookie", cookies);
  if (process.env.THEOS_FRONTEND_SECRET)
    headers.set("x-theos-frontend-secret", process.env.THEOS_FRONTEND_SECRET);
  const clientHeader = process.env.THEOS_CLIENT_IP_HEADER;
  if (clientHeader) {
    const address = request.headers.get(clientHeader)?.split(",", 1)[0].trim();
    if (address && isIP(address)) headers.set("x-theos-client-ip", address);
  }
  const url = new URL(base);
  // Assign the pathname without interpreting client segments as an upstream URL.
  url.pathname = path;
  url.search = new URL(request.url).search;
  let upstream;
  try {
    upstream = await upstreamFetch(url, {
      dispatcher,
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      duplex: "half",
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch (error) {
    if (request.signal.aborted) throw error;
    return Response.json(
      { detail: "The application service is unavailable. Try again shortly." },
      { status: 502 },
    );
  }
  const responseHeaders = new Headers({
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy":
      "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
  });
  for (const name of ["content-type", "content-disposition", "retry-after"])
    if (upstream.headers.has(name))
      responseHeaders.set(name, upstream.headers.get(name));
  if (upstream.headers.get("location") === "/?connections=1")
    responseHeaders.set("location", "/?connections=1");
  for (const cookie of upstream.headers.getSetCookie())
    responseHeaders.append("set-cookie", cookie);
  if (upstream.headers.get("content-type")?.startsWith("text/event-stream"))
    responseHeaders.set("X-Accel-Buffering", "no");
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}
