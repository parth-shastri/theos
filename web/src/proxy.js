import { randomBytes } from "node:crypto";
import { NextResponse } from "next/server";

export function proxy(request) {
  const nonce = randomBytes(32).toString("base64");
  const development = process.env.NODE_ENV === "development";
  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    development
      ? "style-src 'self' 'unsafe-inline'"
      : `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "media-src 'self' blob:",
    `connect-src 'self'${development ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
  ].join("; ");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "no-referrer");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), geolocation=(), microphone=(self)",
  );
  response.headers.set("Cache-Control", "no-store");
  if (process.env.AGENT_WEB_URL?.startsWith("https://"))
    response.headers.set("Strict-Transport-Security", "max-age=31536000");
  return response;
}

export const config = {
  // API handlers validate origins themselves. Keep upload bodies out of Proxy buffering.
  matcher: [
    "/((?!api/|oauth/|webhooks/|ready|_next/static|_next/image|static/|favicon.ico).*)",
  ],
};
