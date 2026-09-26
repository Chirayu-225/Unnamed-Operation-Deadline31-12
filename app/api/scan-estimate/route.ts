const SERVICE_URL = process.env.PYTHON_SERVICE_URL ?? "http://localhost:8000";

// Thin proxy to the Python service's stateless /scans/estimate endpoint —
// same seam and same reasoning as app/api/scan/route.ts (kept server-side
// so the frontend never needs to know PYTHON_SERVICE_URL or attach an
// auth token itself once auth exists). This one is called from
// ScanForm's preflight effect, not from a form submit, so it's expected
// to fire far more often and far more transiently — a user swapping
// file choices a few times before settling cancels several of these via
// AbortController on the client side, which is normal, not an error.
export async function POST(request: Request) {
  try {
    const incomingForm = await request.formData();
    const res = await fetch(`${SERVICE_URL}/scans/estimate`, {
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
