import Link from "next/link";

import { type AlertSummary, type Axis, fetchWatchlistFeed } from "@/lib/api";

const AXIS_STYLES: Record<Axis, { label: string; className: string }> = {
  permit:    { label: "PERMIT",    className: "bg-amber-500/15 text-amber-300 ring-amber-500/30" },
  flood:     { label: "FLOOD",     className: "bg-sky-500/15 text-sky-300 ring-sky-500/30" },
  zoning:    { label: "ZONING",    className: "bg-violet-500/15 text-violet-300 ring-violet-500/30" },
  ownership: { label: "OWNERSHIP", className: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30" },
  market:    { label: "MARKET",    className: "bg-rose-500/15 text-rose-300 ring-rose-500/30" },
};

export default async function WatchlistPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const feed = await fetchWatchlistFeed(id, { limit: 50 });

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-12">
      <header className="mb-10 space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
          Watchlist · {id.slice(0, 8)}
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {feed.total} {feed.total === 1 ? "alert" : "alerts"}
        </h1>
        <p className="text-sm text-zinc-500">
          Live materiality screen against the demo watchlist&apos;s deal thesis. Click any
          alert to see the decision trace.
        </p>
      </header>

      {feed.items.length === 0 ? (
        <EmptyState />
      ) : (
        <ol className="space-y-3">
          {feed.items.map((alert) => (
            <li key={alert.alert_id}>
              <AlertRow watchlistId={id} alert={alert} />
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}

function AlertRow({
  watchlistId,
  alert,
}: {
  watchlistId: string;
  alert: AlertSummary;
}) {
  const isFixture = alert.classifier_tier === "haiku" && alert.materiality_score === 0;
  const axisStyle = AXIS_STYLES[alert.axis];
  const score = alert.materiality_score;
  const scoreTone =
    score >= 80 ? "text-rose-300"
    : score >= 60 ? "text-amber-300"
    : score >= 40 ? "text-zinc-300"
    : "text-zinc-500";

  return (
    <Link
      href={`/w/${watchlistId}/alert/${alert.alert_id}`}
      className="block rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 transition hover:border-zinc-700 hover:bg-zinc-900/50"
    >
      <div className="flex items-start gap-4">
        <span
          className={`shrink-0 rounded-full px-2.5 py-0.5 font-mono text-[10px] font-semibold ring-1 ring-inset ${axisStyle.className}`}
        >
          {axisStyle.label}
        </span>
        <span className={`shrink-0 font-mono text-sm font-semibold tabular-nums ${scoreTone}`}>
          {String(score).padStart(2, " ")}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug text-zinc-100">{alert.summary}</p>
          <p className="mt-1 font-mono text-xs text-zinc-500">
            <span className="tabular-nums">{alert.parcel_apn.trim()}</span>
            <span className="px-2 text-zinc-700">·</span>
            <span>{formatRelativeTime(alert.created_at)}</span>
            {isFixture && (
              <>
                <span className="px-2 text-zinc-700">·</span>
                <span className="text-zinc-600">fixture</span>
              </>
            )}
          </p>
        </div>
      </div>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-zinc-800 p-12 text-center">
      <p className="text-sm text-zinc-500">
        No alerts yet. Run <code className="font-mono text-zinc-400">parcelpulse-scheduler</code> to
        ingest permits, then run{" "}
        <code className="font-mono text-zinc-400">scripts/seed_fixture_alerts.py</code> for fixture
        UI content.
      </p>
    </div>
  );
}

function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const seconds = Math.max(0, Math.floor((now - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
