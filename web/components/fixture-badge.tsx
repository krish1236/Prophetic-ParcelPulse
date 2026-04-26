/**
 * Small "fixture" pill rendered on alerts whose triggering event came from a
 * `fixture_*` adapter. Keeps the demo honest: real alerts and synthetic ones
 * are visually distinguishable everywhere they appear.
 */
export function FixtureBadge({ className = "" }: { className?: string }) {
  return (
    <span
      title="Triggering event was synthesized from a fixture file, not a real public source."
      className={`rounded-full border border-zinc-800 px-1.5 py-px font-mono text-[9px] uppercase tracking-wider text-zinc-500 ${className}`}
    >
      fixture
    </span>
  );
}
