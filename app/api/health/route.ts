const SERVICE_URL = process.env.PYTHON_SERVICE_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const res = await fetch(`${SERVICE_URL}/health`, { cache: "no-store" });
    const data = await res.json();
    return Response.json({ frontend: "ok", service: data });
  } catch {
    return Response.json(
      { frontend: "ok", service: "unreachable" },
      { status: 503 }
    );
  }
}
