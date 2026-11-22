const actions = new Set(["trip", "itinerary", "chat"]);

export async function POST(request: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!actions.has(action)) return Response.json({ detail: "Unknown planner action." }, { status: 404 });
  const raw = await request.text();
  if (raw.length > 24_000) return Response.json({ detail: "Planning request is too long." }, { status: 413 });
  try {
    const response = await fetch(`http://127.0.0.1:8000/api/planner/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: raw,
      signal: AbortSignal.timeout(action === "trip" ? 22_000 : 100_000),
    });
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ detail: "The planner is temporarily unavailable." }, { status: 502 });
  }
}
