import { fetchHealth } from "@/lib/api";

export default async function Home() {
  const health = await fetchHealth();

  return (
    <main className="flex flex-1 flex-col items-center justify-center px-6 py-24">
      <div className="mx-auto max-w-3xl space-y-8 text-center">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
          ParcelPulse
        </p>
        <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
          The event-sourced change feed for parcel watchlists.
        </h1>
        <p className="mx-auto max-w-2xl text-lg leading-relaxed text-zinc-500">
          Homebuilders watch 500 parcels at a time. Permits, zoning, ownership, FEMA, listings —
          all change quietly across 3,000+ counties. ParcelPulse turns those signals into
          ranked, evidenced &ldquo;act on this&rdquo; alerts.
        </p>
        <HealthBadge ok={health.ok} status={health.status} />
      </div>
    </main>
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
