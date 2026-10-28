import { forwardToBackend } from "../../../server/backend";
import { cachedImage } from "../../../server/search-images";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request) {
  const authURL = new URL("/api/me", request.url);
  const identity = await forwardToBackend(
    new Request(authURL, {
      headers: request.headers,
      signal: request.signal,
    }),
    "/api/me",
  );
  await identity.body?.cancel();
  if (!identity.ok)
    return new Response(null, {
      status: identity.status,
      headers: { "Cache-Control": "no-store" },
    });
  try {
    const params = new URL(request.url).searchParams;
    const site = params.get("site");
    const image = await cachedImage(
      site || params.get("url"),
      site ? "logo" : "image",
    );
    return new Response(image.bytes, {
      headers: {
        "Content-Type": image.type,
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Referrer-Policy": "no-referrer",
      },
    });
  } catch {
    return new Response(null, {
      status: 404,
      headers: { "Cache-Control": "no-store" },
    });
  }
}
