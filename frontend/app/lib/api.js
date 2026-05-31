/**
 * ApexSim AI – API client for the FastAPI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `API error ${res.status}`);
  }
  return res.json();
}

export async function fetchEvents(year) {
  return apiFetch(`/api/events?year=${year}`);
}

export async function fetchSessions(year, eventRound) {
  return apiFetch(`/api/sessions?year=${year}&event_round=${eventRound}`);
}

export async function fetchDrivers(year, eventRound, sessionType) {
  return apiFetch(
    `/api/drivers?year=${year}&event_round=${eventRound}&session_type=${encodeURIComponent(sessionType)}`
  );
}

export async function fetchTelemetry(year, eventRound, sessionType, driver1, driver2) {
  return apiFetch(
    `/api/telemetry?year=${year}&event_round=${eventRound}` +
      `&session_type=${encodeURIComponent(sessionType)}` +
      `&driver1=${encodeURIComponent(driver1)}` +
      `&driver2=${encodeURIComponent(driver2)}`
  );
}

export async function fetchInsight(waypoint, insightMode, context) {
  return apiFetch("/api/insight", {
    method: "POST",
    body: JSON.stringify({
      waypoint,
      insight_mode: insightMode,
      ...context,
    }),
  });
}

export async function fetchLapInsight(lapSummary, insightMode, context) {
  return apiFetch("/api/lap-insight", {
    method: "POST",
    body: JSON.stringify({
      ...lapSummary,
      insight_mode: insightMode,
      ...context,
    }),
  });
}

export async function fetchHealth() {
  return apiFetch("/api/health");
}
