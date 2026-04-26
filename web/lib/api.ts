const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const DEMO_WATCHLIST_ID = "00000000-0000-0000-0000-000000000001";

export type Axis = "zoning" | "flood" | "permit" | "ownership" | "market";
export type ClassifierTier = "rules" | "haiku" | "sonnet";

export type SourceStatus = {
  name: string;
  last_ingested_at: string | null;
  lag_seconds: number | null;
  paused: boolean;
};

export type Health = {
  ok: boolean;
  status: string;
  sources: SourceStatus[];
};

export type AlertSummary = {
  alert_id: string;
  watchlist_id: string;
  parcel_id: string;
  parcel_apn: string;
  triggering_event_id: string;
  event_source: string;
  axis: Axis;
  materiality_score: number;
  confidence: number;
  summary: string;
  classifier_tier: ClassifierTier;
  created_at: string;
};

export type AlertFeedResponse = {
  items: AlertSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type AlertDetail = {
  alert_id: string;
  watchlist_id: string;
  parcel_id: string;
  parcel_apn: string;
  parcel_address: string | null;
  triggering_event_id: string;
  event_source: string;
  event_type: string;
  event_payload: Record<string, unknown>;
  axis: Axis;
  materiality_score: number;
  confidence: number;
  summary: string;
  decision_trace: Record<string, unknown>;
  classifier_tier: ClassifierTier;
  created_at: string;
};

export async function fetchHealth(): Promise<Health> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, status: `error ${res.status}`, sources: [] };
    }
    const data = (await res.json()) as { status: string; sources?: SourceStatus[] };
    return { ok: data.status === "ok", status: data.status, sources: data.sources ?? [] };
  } catch {
    return { ok: false, status: "unreachable", sources: [] };
  }
}

export type FeedQuery = {
  from?: string;
  to?: string;
  axis?: Axis;
  min_score?: number;
  limit?: number;
  offset?: number;
};

export async function fetchWatchlistFeed(
  watchlistId: string,
  query: FeedQuery = {},
): Promise<AlertFeedResponse> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const qs = params.toString();
  const url = `${API_BASE_URL}/watchlists/${watchlistId}/feed${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`feed fetch failed: ${res.status}`);
  return (await res.json()) as AlertFeedResponse;
}

export async function fetchAlert(alertId: string): Promise<AlertDetail> {
  const res = await fetch(`${API_BASE_URL}/alerts/${alertId}`, { cache: "no-store" });
  if (!res.ok) {
    if (res.status === 404) {
      throw new Error("alert not found");
    }
    throw new Error(`alert fetch failed: ${res.status}`);
  }
  return (await res.json()) as AlertDetail;
}

export type ReplayAlert = {
  event_id: string;
  parcel_id: string;
  parcel_apn: string;
  event_source: string;
  axis: Axis;
  materiality_score: number;
  confidence: number;
  summary: string;
  classifier_tier: ClassifierTier;
  occurred_at: string;
};

export type ReplayResponse = {
  run_id: string;
  from_ts: string;
  to_ts: string;
  alerts: ReplayAlert[];
  candidate_total: number;
  skipped_for_cache_miss: number;
  cache_hit_pct: number;
  duration_ms: number;
  ran_at: string;
};

export async function postReplay(req: {
  watchlist_id: string;
  from_ts: string;
  to_ts: string;
}): Promise<ReplayResponse> {
  const res = await fetch(`${API_BASE_URL}/replay`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`replay failed: ${res.status}`);
  return (await res.json()) as ReplayResponse;
}
