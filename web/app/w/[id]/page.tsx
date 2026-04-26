import Link from "next/link";

import { FixtureBadge } from "@/components/fixture-badge";
import { ParcelMap } from "@/components/parcel-map";
import { type AlertSummary, fetchWatchlistFeed } from "@/lib/api";
import { AXIS_STYLES, formatRelativeTime, isFixtureSource, scoreTone } from "@/lib/ui";

export default async function WatchlistPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const feed = await fetchWatchlistFeed(id, { limit: 50 });

  return (
    <main className="mx-auto w-full max-w-7xl px-6 py-10">
      <header className="mb-8 flex items-start justify-between gap-6">
        <div className="space-y-2">
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
        </div>
        <Link
          href={`/w/${id}/replay`}
          className="shrink-0 rounded-md border border-zinc-800 px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200"
        >
          replay →
        </Link>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        <section className="lg:col-span-2">
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
        </section>

        <section className="lg:col-span-3">
          <div className="lg:sticky lg:top-6">
            <ParcelMap
              watchlistId={id}
              className="h-[55vh] w-full overflow-hidden rounded-lg border border-zinc-800 lg:h-[calc(100vh-7rem)]"
            />
            <MapLegend />
          </div>
        </section>
      </div>
    </main>
  );
}

function MapLegend() {
  const axes: Array<{ axis: keyof typeof AXIS_STYLES; color: string }> = [
    { axis: "permit", color: "#f59e0b" },
    { axis: "flood", color: "#0ea5e9" },
    { axis: "zoning", color: "#a855f7" },
    { axis: "ownership", color: "#10b981" },
    { axis: "market", color: "#f43f5e" },
  ];
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 px-1 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
      <span>parcels</span>
      <span className="inline-flex items-center gap-1.5">
        <span className="block h-2 w-3 rounded-sm border border-blue-500 bg-blue-500/20" />
        watched
      </span>
      <span className="ml-2 text-zinc-700">·</span>
      <span>alerts</span>
      {axes.map((a) => (
        <span key={a.axis} className="inline-flex items-center gap-1.5">
          <span
            className="block h-2 w-2 rounded-full"
            style={{ backgroundColor: a.color }}
          />
          {a.axis}
        </span>
      ))}
    </div>
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
  const fixture = isFixtureSource(alert.event_source);
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
          <p className="mt-1 flex flex-wrap items-center gap-x-2 font-mono text-xs text-zinc-500">
            <span className="tabular-nums">{alert.parcel_apn.trim()}</span>
            <span className="text-zinc-700">·</span>
            <span>{formatRelativeTime(alert.created_at)}</span>
            {fixture && <FixtureBadge />}
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
