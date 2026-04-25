const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type Health = {
  ok: boolean;
  status: string;
};

export async function fetchHealth(): Promise<Health> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!res.ok) return { ok: false, status: `error ${res.status}` };
    const data = (await res.json()) as { status: string };
    return { ok: data.status === "ok", status: data.status };
  } catch {
    return { ok: false, status: "unreachable" };
  }
}
