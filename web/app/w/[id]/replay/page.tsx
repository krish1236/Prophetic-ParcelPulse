"use client";

import * as Slider from "@radix-ui/react-slider";
import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FixtureBadge } from "@/components/fixture-badge";
import { type ReplayAlert, type ReplayResponse, postReplay } from "@/lib/api";
import { AXIS_STYLES, formatRelativeTime, isFixtureSource, scoreTone } from "@/lib/ui";

const WINDOW_MAX_DAYS = 90;
const DEFAULT_RANGE: [number, number] = [0, 30];
const DEBOUNCE_MS = 200;

export default function ReplayPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [range, setRange] = useState<[number, number]>(DEFAULT_RANGE);
  const [data, setData] = useState<ReplayResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fromTs = useMemo(() => isoFromDaysAgo(range[1]), [range]);
  const toTs = useMemo(() => isoFromDaysAgo(range[0]), [range]);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runReplay = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await postReplay({ watchlist_id: id, from_ts: fromTs, to_ts: toTs });
      setData(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "replay failed");
    } finally {
      setLoading(false);
    }
  }, [id, fromTs, toTs]);

  // Initial load + debounced re-run on slider change.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void runReplay();
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [runReplay]);

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10">
      <Link
        href={`/w/${id}`}
        className="inline-flex items-center gap-2 text-sm text-zinc-500 transition hover:text-zinc-300"
      >
        ← back to watchlist
      </Link>

      <header className="mt-6 mb-8 space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
          Replay
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          What would you have been alerted on?
        </h1>
        <p className="text-sm text-zinc-500">
          Drag the handles to a date window. Replays are deterministic — same
          window → same alerts, no live LLM calls.
        </p>
      </header>

      <RangeSlider value={range} onValueChange={setRange} />
      <WindowLabel from={fromTs} to={toTs} range={range} />
      <Provenance loading={loading} data={data} error={error} />

      <div className="mt-8">
        {loading && !data ? (
          <Skeleton />
        ) : data && data.alerts.length === 0 ? (
          <EmptyState skipped={data.skipped_for_cache_miss} />
        ) : data ? (
          <ol className="space-y-3">
            {data.alerts.map((a) => (
              <li key={a.event_id + a.parcel_id}>
                <AlertRow watchlistId={id} alert={a} />
              </li>
            ))}
          </ol>
        ) : null}
      </div>
    </main>
  );
}

function RangeSlider({
  value,
  onValueChange,
}: {
  value: [number, number];
  onValueChange: (v: [number, number]) => void;
}) {
  return (
    <Slider.Root
      className="relative flex h-6 w-full touch-none select-none items-center"
      value={value}
      onValueChange={(v) => onValueChange([v[0], v[1]] as [number, number])}
      min={0}
      max={WINDOW_MAX_DAYS}
      step={1}
      minStepsBetweenThumbs={1}
      inverted
    >
      <Slider.Track className="relative h-1 grow rounded-full bg-zinc-800">
        <Slider.Range className="absolute h-full rounded-full bg-sky-500/70" />
      </Slider.Track>
      <Slider.Thumb
        aria-label="To date"
        className="block h-4 w-4 rounded-full border border-sky-400 bg-zinc-950 transition hover:scale-110 focus:outline-none focus:ring-2 focus:ring-sky-500/40"
      />
      <Slider.Thumb
        aria-label="From date"
        className="block h-4 w-4 rounded-full border border-sky-400 bg-zinc-950 transition hover:scale-110 focus:outline-none focus:ring-2 focus:ring-sky-500/40"
      />
    </Slider.Root>
  );
}

function WindowLabel({
  from,
  to,
  range,
}: {
  from: string;
  to: string;
  range: [number, number];
}) {
  const fromDate = new Date(from).toLocaleDateString();
  const toDate = new Date(to).toLocaleDateString();
  return (
    <p className="mt-3 font-mono text-xs text-zinc-500">
      <span>{fromDate}</span>
      <span className="px-2 text-zinc-700">→</span>
      <span>{toDate}</span>
      <span className="px-2 text-zinc-700">·</span>
      <span>
        {range[1] - range[0]} day{range[1] - range[0] === 1 ? "" : "s"} window
      </span>
    </p>
  );
}

function Provenance({
  loading,
  data,
  error,
}: {
  loading: boolean;
  data: ReplayResponse | null;
  error: string | null;
}) {
  if (error) {
    return (
      <p className="mt-4 font-mono text-xs text-rose-400">replay error: {error}</p>
    );
  }
  if (!data) {
    return (
      <p className="mt-4 font-mono text-xs text-zinc-600">
        {loading ? "running…" : "—"}
      </p>
    );
  }
  return (
    <p className="mt-4 font-mono text-xs text-zinc-500">
      <span>ran in {data.duration_ms}ms</span>
      <span className="px-2 text-zinc-700">·</span>
      <span>{data.cache_hit_pct.toFixed(1)}% cache hit</span>
      <span className="px-2 text-zinc-700">·</span>
      <span>
        {data.alerts.length} alert{data.alerts.length === 1 ? "" : "s"}
      </span>
      {data.skipped_for_cache_miss > 0 && (
        <>
          <span className="px-2 text-zinc-700">·</span>
          <span className="text-zinc-600">
            {data.skipped_for_cache_miss} skipped (not classified at the time)
          </span>
        </>
      )}
      {loading && (
        <>
          <span className="px-2 text-zinc-700">·</span>
          <span className="text-zinc-600">refreshing…</span>
        </>
      )}
    </p>
  );
}

function AlertRow({
  watchlistId,
  alert,
}: {
  watchlistId: string;
  alert: ReplayAlert;
}) {
  const axisStyle = AXIS_STYLES[alert.axis];
  const fixture = isFixtureSource(alert.event_source);
  // Replay produces synthetic alerts (no stable alert_id), so the row is
  // intentionally non-clickable — the real alert (if any) lives on the
  // watchlist feed.
  void watchlistId;
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">
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
            <span>{formatRelativeTime(alert.occurred_at)}</span>
            <span className="text-zinc-700">·</span>
            <span className="uppercase">{alert.classifier_tier}</span>
            {fixture && <FixtureBadge />}
          </p>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ skipped }: { skipped: number }) {
  return (
    <div className="rounded-lg border border-dashed border-zinc-800 p-12 text-center">
      <p className="text-sm text-zinc-500">
        No alerts in this window.
        {skipped > 0 && (
          <>
            {" "}
            <span className="text-zinc-600">
              {skipped} candidate{skipped === 1 ? "" : "s"} skipped — not yet
              classified at the time.
            </span>
          </>
        )}
      </p>
    </div>
  );
}

function Skeleton() {
  return (
    <ol className="space-y-3">
      {[0, 1, 2].map((i) => (
        <li
          key={i}
          className="h-16 animate-pulse rounded-lg border border-zinc-900 bg-zinc-950/30"
        />
      ))}
    </ol>
  );
}

function isoFromDaysAgo(daysAgo: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - daysAgo);
  return d.toISOString();
}
