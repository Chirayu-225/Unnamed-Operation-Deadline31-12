const SERVICE_URL = process.env.PYTHON_SERVICE_URL ?? "http://localhost:8000";

// Thin proxy to the Python service's stateless /scans endpoint. Kept as
// a server-side route (rather than the browser calling :8000 directly)
// for the same reason the /health proxy exists — this is the seam
// where an auth token gets attached server-side once auth exists,
// without the frontend's scan-submitting code needing to change.
export async function POST(request: Request) {
  try {
    const incomingForm = await request.formData();
    const res = await fetch(`${SERVICE_URL}/scans`, {
      method: "POST",
      body: incomingForm,
      cache: "no-store",
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch (err) {
    return Response.json(
      {
        error: "Could not reach the Python service.",
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 503 }
    );
  }
}
