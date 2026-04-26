import Link from "next/link";
import { notFound } from "next/navigation";

import { DecisionTrace, type Trace } from "@/components/decision-trace";
import { type AlertDetail, fetchAlert } from "@/lib/api";
import { AXIS_STYLES, formatRelativeTime, scoreTone } from "@/lib/ui";

export default async function AlertDetailPage({
  params,
}: {
  params: Promise<{ id: string; alertId: string }>;
}) {
  const { id, alertId } = await params;

  let alert: AlertDetail;
  try {
    alert = await fetchAlert(alertId);
  } catch {
    notFound();
  }

  const trace = (alert.decision_trace ?? {}) as Trace;
  const axisStyle = AXIS_STYLES[alert.axis];
  const isFixture = trace.fixture === true;
  const isPlaceholder = trace.placeholder === true;

  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-10">
      <Link
        href={`/w/${id}`}
        className="inline-flex items-center gap-2 text-sm text-zinc-500 transition hover:text-zinc-300"
      >
        ← back to watchlist
      </Link>

      <header className="mt-6 space-y-3">
        <div className="flex items-center gap-3">
          <span
            className={`rounded-full px-2.5 py-0.5 font-mono text-[10px] font-semibold ring-1 ring-inset ${axisStyle.className}`}
          >
            {axisStyle.label}
          </span>
          <span
            className={`font-mono text-2xl font-semibold tabular-nums ${scoreTone(alert.materiality_score)}`}
          >
            {alert.materiality_score}
          </span>
          <span className="font-mono text-xs text-zinc-500">
            confidence {Math.round(alert.confidence * 100)}%
          </span>
          {isFixture && (
            <span className="ml-auto rounded-full border border-zinc-800 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
              fixture data
            </span>
          )}
          {isPlaceholder && !isFixture && (
            <span className="ml-auto rounded-full border border-zinc-800 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
              tier 1 only
            </span>
          )}
        </div>

        <h1 className="text-2xl font-semibold leading-snug tracking-tight">
          {alert.summary}
        </h1>

        <p className="font-mono text-xs text-zinc-500">
          <span className="tabular-nums">{alert.parcel_apn.trim()}</span>
          {alert.parcel_address && (
            <>
              <span className="px-2 text-zinc-700">·</span>
              <span>{alert.parcel_address.trim()}</span>
            </>
          )}
          <span className="px-2 text-zinc-700">·</span>
          <span>{formatRelativeTime(alert.created_at)}</span>
          <span className="px-2 text-zinc-700">·</span>
          <span className="uppercase">{alert.classifier_tier}</span>
        </p>
      </header>

      <div className="mt-10 space-y-8">
        <DecisionTrace trace={trace} />

        <section>
          <h2 className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
            Triggering event
          </h2>
          <div className="rounded border border-zinc-800 bg-zinc-950/50 p-4">
            <p className="font-mono text-xs text-zinc-500">
              <span>{alert.event_source}</span>
              <span className="px-2 text-zinc-700">·</span>
              <span>{alert.event_type}</span>
            </p>
            <pre className="mt-3 max-h-72 overflow-auto rounded bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
              {JSON.stringify(alert.event_payload, null, 2)}
            </pre>
          </div>
        </section>
      </div>
    </main>
  );
}
