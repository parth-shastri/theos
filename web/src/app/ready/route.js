export const dynamic = "force-dynamic";

export async function GET() {
  let ready = false;
  try {
    const secret = process.env.THEOS_FRONTEND_SECRET || "";
    if (secret.length >= 32) {
      const base = new URL(
        process.env.THEOS_API_URL || "http://127.0.0.1:8080",
      );
      const response = await fetch(new URL("/ready", base), {
        cache: "no-store",
        headers: { "X-Theos-Frontend-Secret": secret },
        signal: AbortSignal.timeout(3000),
      });
      const value = await response.json();
      ready = response.ok && value.status === "ready";
    }
  } catch {
    ready = false;
  }
  return Response.json(
    { status: ready ? "ready" : "not_ready" },
    { status: ready ? 200 : 503, headers: { "Cache-Control": "no-store" } },
  );
}
