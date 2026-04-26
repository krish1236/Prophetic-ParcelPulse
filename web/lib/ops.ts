const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type OpsSourceStatus = {
  name: string;
  last_ingested_at: string | null;
  lag_seconds: number | null;
  paused: boolean;
};

export type OpsIngestRow = { day: string; source: string; events: number };
export type OpsCostRow = { day: string; tier: string; cost_usd: number };

export type OpsMetrics = {
  sources: OpsSourceStatus[];
  ingest_by_day: OpsIngestRow[];
  cost_by_day: OpsCostRow[];
  cost_today_usd: number;
  cost_cap_usd: number;
};

export async function fetchOpsMetrics(token: string | null): Promise<OpsMetrics> {
  const res = await fetch(`${API_BASE_URL}/admin/ops/metrics`, {
    headers: token ? { "X-Ops-Token": token } : undefined,
    cache: "no-store",
  });
  if (res.status === 401) throw new Error("invalid token");
  if (!res.ok) throw new Error(`metrics fetch failed: ${res.status}`);
  return (await res.json()) as OpsMetrics;
}
