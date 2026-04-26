/**
 * Renders the structured Tier-2 decision trace card.
 *
 * Handles three shapes that may land in `alerts.decision_trace`:
 *   - Full Sonnet output  (what_changed / why_it_matters / evidence / next_step)
 *   - Fixture data        (same shape + `fixture: true`)
 *   - Tier-1 placeholder  (`placeholder: true`) — renders a quiet note instead.
 */

import type { ReactNode } from "react";

export type Trace = {
  fixture?: boolean;
  placeholder?: boolean;
  tier?: string;
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

export function DecisionTrace({ trace }: { trace: Trace }) {
  if (trace.placeholder) {
    return (
      <Section title="Decision trace">
        <p className="text-sm text-zinc-500">
          Tier 2 (Sonnet) didn&apos;t run for this alert — score below threshold or
          budget exhausted. The Tier 1 summary above is the briefing.
        </p>
      </Section>
    );
  }

  return (
    <>
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
              <li key={i} className="rounded border border-zinc-800 bg-zinc-950/50 p-3">
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
                {e.captured_at && (
                  <p className="mt-1 font-mono text-[11px] text-zinc-600">
                    captured {new Date(e.captured_at).toLocaleString()}
                  </p>
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
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
        {title}
      </h2>
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
