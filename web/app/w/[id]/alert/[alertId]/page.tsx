import Link from "next/link";
import { notFound } from "next/navigation";

import { type AlertDetail, fetchAlert } from "@/lib/api";
import { AXIS_STYLES, formatRelativeTime, scoreTone } from "@/lib/ui";

type Trace = {
  fixture?: boolean;
  what_changed?: string;
  why_it_matters?: string;
  evidence?: Array<{
    label?: string;
    source_url?: string;
    snippet?: string;
    captured_at?: string | null;
  }>;
  next_step?: {
    action?: string;
    urgency?: "now" | "this_week" | "fyi" | string;
    owner_role?: string;
  };
};

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
        {trace.what_changed && (
          <Section title="What changed">
            <p className="text-sm leading-relaxed text-zinc-200">{trace.what_changed}</p>
          </Section>
        )}

        {trace.why_it_matters && (
          <Section title="Why it matters">
            <p className="text-sm leading-relaxed text-zinc-200">{trace.why_it_matters}</p>
          </Section>
        )}

        {trace.evidence && trace.evidence.length > 0 && (
          <Section title="Evidence">
            <ul className="space-y-3">
              {trace.evidence.map((e, i) => (
                <li
                  key={i}
                  className="rounded border border-zinc-800 bg-zinc-950/50 p-3"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-mono text-xs uppercase tracking-wider text-zinc-500">
                      {e.label ?? "source"}
                    </span>
                    {e.source_url && (
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-mono text-xs text-sky-400 hover:text-sky-300"
                      >
                        open ↗
                      </a>
                    )}
                  </div>
                  {e.snippet && (
                    <p className="mt-1 text-sm leading-snug text-zinc-300">{e.snippet}</p>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {trace.next_step && (
          <Section title="Suggested next step">
            <div className="rounded border border-zinc-800 bg-zinc-950/50 p-4">
              <div className="mb-2 flex items-center gap-3">
                <UrgencyBadge urgency={trace.next_step.urgency} />
                {trace.next_step.owner_role && (
                  <span className="font-mono text-xs text-zinc-500">
                    owner: {trace.next_step.owner_role.replaceAll("_", " ")}
                  </span>
                )}
              </div>
              {trace.next_step.action && (
                <p className="text-sm leading-snug text-zinc-200">{trace.next_step.action}</p>
              )}
            </div>
          </Section>
        )}

        <Section title="Triggering event">
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
        </Section>
      </div>
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">{title}</h2>
      {children}
    </section>
  );
}

function UrgencyBadge({ urgency }: { urgency?: string }) {
  const styles: Record<string, string> = {
    now: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
    this_week: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
    fyi: "bg-zinc-800/50 text-zinc-400 ring-zinc-700",
  };
  const cls = (urgency && styles[urgency]) ?? styles.fyi;
  const label = urgency ? urgency.replaceAll("_", " ") : "fyi";
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 font-mono text-[10px] font-semibold uppercase ring-1 ring-inset ${cls}`}
    >
      {label}
    </span>
  );
}
