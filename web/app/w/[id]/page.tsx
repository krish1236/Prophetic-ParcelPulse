import Link from "next/link";

import { type AlertSummary, fetchWatchlistFeed } from "@/lib/api";
import { AXIS_STYLES, formatRelativeTime, scoreTone } from "@/lib/ui";

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
  const axisStyle = AXIS_STYLES[alert.axis];
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
        <span
          className={`shrink-0 font-mono text-sm font-semibold tabular-nums ${scoreTone(alert.materiality_score)}`}
        >
          {String(alert.materiality_score).padStart(2, " ")}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-snug text-zinc-100">{alert.summary}</p>
          <p className="mt-1 font-mono text-xs text-zinc-500">
            <span className="tabular-nums">{alert.parcel_apn.trim()}</span>
            <span className="px-2 text-zinc-700">·</span>
            <span>{formatRelativeTime(alert.created_at)}</span>
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
