import Link from "next/link";

import { FixtureBadge } from "@/components/fixture-badge";
import {
  DEMO_WATCHLIST_ID,
  type AlertSummary,
  fetchHealth,
  fetchWatchlistFeed,
} from "@/lib/api";
import { AXIS_STYLES, formatRelativeTime, isFixtureSource, scoreTone } from "@/lib/ui";

export default async function Home() {
  const [health, feed] = await Promise.all([
    fetchHealth(),
    fetchWatchlistFeed(DEMO_WATCHLIST_ID, { limit: 5 }),
  ]);

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-16">
      <Hero ok={health.ok} status={health.status} />

      <section className="mt-16">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
            Recent alerts
          </h2>
          <Link
            href={`/w/${DEMO_WATCHLIST_ID}`}
            className="font-mono text-xs text-zinc-400 transition hover:text-zinc-200"
          >
            see full demo watchlist →
          </Link>
        </div>

        {feed.items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center">
            <p className="text-sm text-zinc-500">
              No alerts yet. Run{" "}
              <code className="font-mono text-zinc-400">parcelpulse-scheduler</code> to ingest
              permits, then{" "}
              <code className="font-mono text-zinc-400">scripts/seed_fixture_alerts.py</code>{" "}
              for fixture content.
            </p>
          </div>
        ) : (
          <ol className="divide-y divide-zinc-900 rounded-lg border border-zinc-800 bg-zinc-950/50">
            {feed.items.map((alert) => (
              <li key={alert.alert_id}>
                <AlertPreview alert={alert} />
              </li>
            ))}
          </ol>
        )}
      </section>
    </main>
  );
}

function Hero({ ok, status }: { ok: boolean; status: string }) {
  return (
    <div className="space-y-6 text-center">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">ParcelPulse</p>
      <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
        The event-sourced change feed for parcel watchlists.
      </h1>
      <p className="mx-auto max-w-2xl text-base leading-relaxed text-zinc-500 sm:text-lg">
        Homebuilders watch 500 parcels at a time. Permits, zoning, ownership, FEMA, listings —
        all change quietly across 3,000+ counties. ParcelPulse turns those signals into ranked,
        evidenced &ldquo;act on this&rdquo; alerts.
      </p>
      <HealthBadge ok={ok} status={status} />
    </div>
  );
}

function HealthBadge({ ok, status }: { ok: boolean; status: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 px-3 py-1.5 font-mono text-xs text-zinc-600 dark:border-zinc-800 dark:text-zinc-400">
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
      />
      api: {status}
    </div>
  );
}

function AlertPreview({ alert }: { alert: AlertSummary }) {
  const axisStyle = AXIS_STYLES[alert.axis];
  const fixture = isFixtureSource(alert.event_source);
  return (
    <Link
      href={`/w/${DEMO_WATCHLIST_ID}/alert/${alert.alert_id}`}
      className="block px-4 py-3 transition hover:bg-zinc-900/50"
    >
      <div className="flex items-start gap-3">
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
          <p className="truncate text-sm leading-snug text-zinc-200">{alert.summary}</p>
          <p className="mt-0.5 flex items-center gap-2 truncate font-mono text-[11px] text-zinc-500">
            <span className="truncate">{alert.parcel_apn.trim()}</span>
            <span className="text-zinc-700">·</span>
            <span>{formatRelativeTime(alert.created_at)}</span>
            {fixture && <FixtureBadge />}
          </p>
        </div>
      </div>
    </Link>
  );
}
