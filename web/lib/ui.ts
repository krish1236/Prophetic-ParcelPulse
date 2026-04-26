import type { Axis } from "@/lib/api";

export const AXIS_STYLES: Record<Axis, { label: string; className: string }> = {
  permit:    { label: "PERMIT",    className: "bg-amber-500/15 text-amber-300 ring-amber-500/30" },
  flood:     { label: "FLOOD",     className: "bg-sky-500/15 text-sky-300 ring-sky-500/30" },
  zoning:    { label: "ZONING",    className: "bg-violet-500/15 text-violet-300 ring-violet-500/30" },
  ownership: { label: "OWNERSHIP", className: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30" },
  market:    { label: "MARKET",    className: "bg-rose-500/15 text-rose-300 ring-rose-500/30" },
};

export function scoreTone(score: number): string {
  if (score >= 80) return "text-rose-300";
  if (score >= 60) return "text-amber-300";
  if (score >= 40) return "text-zinc-300";
  return "text-zinc-500";
}

export function isFixtureSource(source: string): boolean {
  return source.startsWith("fixture_");
}

/**
 * Map the backend's `classifier_tier` value (which carries internal model
 * identifiers) to a generic user-facing label. We don't surface specific
 * model names in the UI — the demo's value lives at the engine layer, not
 * in any one model choice.
 */
export function tierLabel(tier: string): string {
  if (tier === "sonnet") return "tier 2";
  if (tier === "haiku") return "tier 1";
  return tier;
}

export function formatRelativeTime(iso: string): string {
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
