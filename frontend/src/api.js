const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

// When the dashboard is served from a different origin than the API, the
// dev proxy is not in play and media has to be addressed absolutely.
const API_ORIGIN = /^https?:\/\//i.test(API_BASE) ? new URL(API_BASE).origin : "";

async function request(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function post(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function startRun() {
  return request("/runs", { method: "POST" }); // { run_id }
}

export async function listRuns() {
  return request("/runs"); // [{ run_id, status, created_at, title, approval }] newest first
}

export async function getRun(runId) {
  return request(`/runs/${runId}`); // { type: "snapshot", state, logs }
}

export async function approveRun(runId, caption) {
  return post(`/runs/${runId}/approve`, { caption: caption || null });
}

export async function rejectRun(runId, note) {
  return post(`/runs/${runId}/reject`, { note: note || null });
}

export async function getSchedule() {
  return request("/schedule");
}

export function mediaUrl(path) {
  if (!path) return null;
  return API_ORIGIN ? `${API_ORIGIN}${path}` : path;
}

export function connectRunSocket(runId, onMessage) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/${runId}`);
  ws.onmessage = (event) => onMessage(JSON.parse(event.data));
  return ws;
}
