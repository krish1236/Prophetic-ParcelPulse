"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  type OpsAlertsRow,
  type OpsCostRow,
  type OpsIngestRow,
  type OpsMetrics,
  type OpsSourceStatus,
  fetchOpsMetrics,
} from "@/lib/ops";

const TOKEN_STORAGE_KEY = "pp_ops_token";

const SOURCE_COLORS: Record<string, string> = {
  multco_permits: "#f59e0b",
  fema_nfhl: "#0ea5e9",
  fixture_zoning: "#a855f7",
  fixture_ownership: "#10b981",
  fixture_listings: "#f43f5e",
};
const TIER_COLORS: Record<string, string> = {
  haiku: "#0ea5e9",
  sonnet: "#a855f7",
  rules: "#71717a",
};
const AXIS_COLORS: Record<string, string> = {
  permit: "#f59e0b",
  flood: "#0ea5e9",
  zoning: "#a855f7",
  ownership: "#10b981",
  market: "#f43f5e",
};

export default function OpsDashboardPage() {
  const [token, setToken] = useState<string>("");
  const [data, setData] = useState<OpsMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Load any prior token from this browser; first fetch happens on mount.
  // localStorage hydration after mount is the recommended SSR-safe pattern;
  // the React 19 set-state-in-effect rule is overly strict for it.
  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(TOKEN_STORAGE_KEY) : "";
    const initial = saved ?? "";
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(initial);
    void load(initial);
  }, []);

  async function load(t: string) {
    setLoading(true);
    setError(null);
    try {
      const m = await fetchOpsMetrics(t || null);
      setData(m);
      if (typeof window !== "undefined") localStorage.setItem(TOKEN_STORAGE_KEY, t);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-10">
      <div className="mb-6 flex items-baseline justify-between">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">Ops</p>
          <h1 className="text-2xl font-semibold tracking-tight">Engineering dashboard</h1>
        </div>
        <Link href="/" className="font-mono text-xs text-zinc-500 hover:text-zinc-300">
          ← home
        </Link>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void load(token);
        }}
        className="mb-8 flex items-center gap-2"
      >
        <input
          type="password"
          placeholder="ops token (leave blank in dev)"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="w-72 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-1.5 font-mono text-xs text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-md border border-zinc-800 px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-zinc-300 transition hover:border-zinc-700 hover:bg-zinc-900"
        >
          {loading ? "loading…" : "refresh"}
        </button>
        {error && <span className="font-mono text-xs text-rose-400">{error}</span>}
      </form>

      {data && (
        <div className="space-y-10">
          <SourceTable sources={data.sources} />
          <Panel
            title="Ingestion (events / day, by source)"
            help="Empty bars = no ingest that day. Stale source = healthcheck visible to oncall."
          >
            <IngestChart rows={data.ingest_by_day} />
          </Panel>
          <Panel
            title="LLM cost (USD / day, by tier)"
            help={`Daily ceiling: $${data.cost_cap_usd.toFixed(2)}. Today: $${data.cost_today_usd.toFixed(4)}.`}
          >
            <CostChart rows={data.cost_by_day} cap={data.cost_cap_usd} />
          </Panel>
          <Panel
            title="Alert volume (last 30 days, by axis)"
            help="A silent axis for >7 days = the source went bad."
          >
            <AlertsChart rows={data.alerts_by_day} />
          </Panel>
        </div>
      )}
    </main>
  );
}

function AlertsChart({ rows }: { rows: OpsAlertsRow[] }) {
  const data = useMemo(() => pivotByDay(rows, "axis", "count"), [rows]);
  const axes = useMemo(() => Array.from(new Set(rows.map((r) => r.axis))).sort(), [rows]);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis dataKey="day" stroke="#71717a" fontSize={11} />
        <YAxis stroke="#71717a" fontSize={11} allowDecimals={false} />
        <Tooltip
          contentStyle={{ background: "#0a0a0a", border: "1px solid #27272a" }}
          labelStyle={{ color: "#d4d4d8" }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {axes.map((a) => (
          <Bar key={a} dataKey={a} stackId="alerts" fill={AXIS_COLORS[a] ?? "#9ca3af"} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function Panel({
  title,
  help,
  children,
}: {
  title: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">{title}</h2>
        {help && <p className="font-mono text-[11px] text-zinc-600">{help}</p>}
      </header>
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">{children}</div>
    </section>
  );
}

function SourceTable({ sources }: { sources: OpsSourceStatus[] }) {
  return (
    <Panel title="Sources">
      <table className="w-full text-left font-mono text-xs">
        <thead className="text-zinc-500">
          <tr>
            <th className="pb-2 pr-4">source</th>
            <th className="pb-2 pr-4">last ingested</th>
            <th className="pb-2 pr-4">lag</th>
            <th className="pb-2">paused</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.name} className="border-t border-zinc-900">
              <td className="py-2 pr-4 text-zinc-200">{s.name}</td>
              <td className="py-2 pr-4 text-zinc-400">
                {s.last_ingested_at ? new Date(s.last_ingested_at).toLocaleString() : "—"}
              </td>
              <td className="py-2 pr-4 text-zinc-400">
                {s.lag_seconds == null ? "—" : formatLag(s.lag_seconds)}
              </td>
              <td className="py-2">
                <span className={s.paused ? "text-rose-400" : "text-emerald-400"}>
                  {s.paused ? "paused" : "ok"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function IngestChart({ rows }: { rows: OpsIngestRow[] }) {
  const data = useMemo(() => pivotByDay(rows, "source", "events"), [rows]);
  const sources = useMemo(() => Array.from(new Set(rows.map((r) => r.source))).sort(), [rows]);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis dataKey="day" stroke="#71717a" fontSize={11} />
        <YAxis stroke="#71717a" fontSize={11} />
        <Tooltip
          contentStyle={{ background: "#0a0a0a", border: "1px solid #27272a" }}
          labelStyle={{ color: "#d4d4d8" }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {sources.map((s) => (
          <Bar key={s} dataKey={s} stackId="ingest" fill={SOURCE_COLORS[s] ?? "#9ca3af"} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function CostChart({ rows, cap }: { rows: OpsCostRow[]; cap: number }) {
  const data = useMemo(() => pivotByDay(rows, "tier", "cost_usd"), [rows]);
  const tiers = useMemo(() => Array.from(new Set(rows.map((r) => r.tier))).sort(), [rows]);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis dataKey="day" stroke="#71717a" fontSize={11} />
        <YAxis stroke="#71717a" fontSize={11} />
        <ReferenceLine y={cap} stroke="#f43f5e" strokeDasharray="4 4" label={{
          value: "cap",
          position: "right",
          fill: "#f43f5e",
          fontSize: 11,
        }} />
        <Tooltip
          contentStyle={{ background: "#0a0a0a", border: "1px solid #27272a" }}
          labelStyle={{ color: "#d4d4d8" }}
          formatter={(v) => `$${(v as number).toFixed(4)}`}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {tiers.map((t) => (
          <Bar key={t} dataKey={t} stackId="cost">
            <Cell fill={TIER_COLORS[t] ?? "#9ca3af"} />
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function pivotByDay<T extends { day: string }>(
  rows: T[],
  keyField: keyof T,
  valueField: keyof T,
): Array<Record<string, string | number>> {
  const days = new Map<string, Record<string, string | number>>();
  for (const r of rows) {
    const k = String(r[keyField]);
    const v = Number(r[valueField] ?? 0);
    if (!days.has(r.day)) days.set(r.day, { day: r.day });
    days.get(r.day)![k] = v;
  }
  return Array.from(days.values()).sort((a, b) =>
    String(a.day).localeCompare(String(b.day)),
  );
}

function formatLag(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}
