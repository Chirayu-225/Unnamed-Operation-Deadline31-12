const SERVICE_URL = process.env.PYTHON_SERVICE_URL ?? "http://localhost:8000";

// Thin proxy to the Python service's /scans/schema endpoint — same
// pattern and same reasoning as app/api/scan/route.ts (server-side seam
// for an eventual auth token, browser never talks to :8000 directly).
export async function POST(request: Request) {
  try {
    const incomingForm = await request.formData();
    const res = await fetch(`${SERVICE_URL}/scans/schema`, {
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
