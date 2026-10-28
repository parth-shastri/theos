import { forwardToBackend } from "../../../server/backend";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function handle(request, { params }) {
  const { path } = await params;
  if (
    path.some(
      (part) =>
        !part || part === "." || part === ".." || /[\\/\u0000]/.test(part),
    )
  )
    return Response.json(
      { detail: "The requested endpoint was not found." },
      { status: 404 },
    );
  return forwardToBackend(
    request,
    `/api/${path.map(encodeURIComponent).join("/")}`,
  );
}

export {
  handle as GET,
  handle as POST,
  handle as PATCH,
  handle as DELETE,
  handle as PUT,
};
