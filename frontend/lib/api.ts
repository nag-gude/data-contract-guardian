/**
 * Server: call FastAPI directly via BACKEND_URL (Cloud Run) or NEXT_PUBLIC_API_URL (local).
 * Client: same-origin `/api` proxy.
 */
async function apiBase(): Promise<string> {
  if (typeof window !== "undefined") return "";
  if (process.env.BACKEND_URL) {
    return process.env.BACKEND_URL.replace(/\/$/, "");
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
}

/** Public backend base URL for links (API docs, health). */
export function backendPublicUrl(): string {
  if (process.env.BACKEND_URL) {
    return process.env.BACKEND_URL.replace(/\/$/, "");
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
}

export async function apiGet<T>(path: string): Promise<T> {
  const base = await apiBase();
  const r = await fetch(`${base}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const base = await apiBase();
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}
