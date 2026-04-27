import Link from "next/link";

export const metadata = {
  title: "Replaying a watchlist from the event log · ParcelPulse",
  description:
    "How the 90-day replay slider stays deterministic without bitemporal snapshots, using the classifier cache as the system's function table.",
};

export default function ReplayPostPage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-16 text-zinc-200">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-zinc-500 transition hover:text-zinc-300"
      >
        ← back to home
      </Link>

      <article className="mt-8 space-y-6">
        <header className="space-y-3 border-b border-zinc-900 pb-6">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight text-zinc-100 sm:text-4xl">
            Replaying a watchlist from the event log
          </h1>
          <p className="font-mono text-xs text-zinc-500">
            April 26, 2026 · 5 minute read
          </p>
        </header>

        <p>
          A land acquisition team has five hundred parcels on a watchlist. Three weeks
          ago, a demolition permit pulled on the parcel next door to one of them. Today
          the team wants to know if their alert system would have caught it on the day.
          Or they want to ask a different question. They want to swap the deal thesis
          from townhomes at eight to twelve units per acre to small multifamily that
          must be in a transit corridor, then see how the alert feed reshapes against
          the same history.
        </p>

        <p>
          Both are the same question. Given a window in the past and a thesis version,
          what would the system have surfaced.
        </p>

        <p>
          ParcelPulse answers it with a slider. Drag the handles over the last ninety
          days and the feed redraws. A small line under the slider reads something like{" "}
          <span className="font-mono text-zinc-400">
            ran in 320ms, 87% cache hit, 14 alerts
          </span>
          . No live LLM calls. The same window dragged twice produces the exact same
          fourteen alerts. This post is about how that works, what the determinism
          contract is, and what we explicitly traded away to keep it cheap.
        </p>

        <h2 className="pt-4 text-xl font-semibold tracking-tight text-zinc-100">
          What we store
        </h2>

        <p>
          Three tables matter for replay. The events table is append only with{" "}
          <span className="font-mono text-zinc-400">
            (source, external_id, payload_hash)
          </span>{" "}
          as the unique key. Every row carries{" "}
          <span className="font-mono text-zinc-400">occurred_at</span> (the real world
          timestamp from the source) and{" "}
          <span className="font-mono text-zinc-400">ingested_at</span> (when we received
          it). Geometry lives as PostGIS multi polygons or points in EPSG 4326.
        </p>

        <p>
          Watchlists carry a{" "}
          <span className="font-mono text-zinc-400">thesis_version</span> integer that
          increments whenever the user edits the deal thesis. The thesis itself is a
          plain English sentence the user wrote, something like townhomes eight to
          twelve units per acre, must clear FEMA zone X.
        </p>

        <p>
          The classifier_cache table holds one row per cache key. The cache key is{" "}
          <span className="font-mono text-zinc-400">
            sha256(event_id, parcel_id, thesis_version, tier)
          </span>
          . The row stores the structured output from the classifier (a materiality
          screen for tier one, a decision trace for tier two) and the dollar cost we
          paid to produce it.
        </p>

        <p>
          Events are facts. The cache is the function output for each fact. Together
          they are the ground truth from which the alert feed is reconstructable.
        </p>

        <h2 className="pt-4 text-xl font-semibold tracking-tight text-zinc-100">
          The replay function
        </h2>

        <p>
          A POST to /replay takes a watchlist id and a date window. It walks every event
          with <span className="font-mono text-zinc-400">occurred_at</span> in the
          window. For each event, tier zero runs the spatial join to find which watched
          parcels the event geographically attributes to. For each candidate, tier one
          and tier two run in cache only mode.
        </p>

        <pre className="overflow-x-auto rounded border border-zinc-800 bg-black/40 p-4 text-[12px] leading-relaxed text-zinc-300">
          <code>{`async def screen(event_id, parcel_id, watchlist_id, session,
                 *, use_cache_only=False):
    key = cache_key(event_id, parcel_id, thesis_version)
    cached = await cache_get(session, key)
    if cached is not None:
        return MaterialityScreen.model_validate(cached)
    if use_cache_only:
        return None
    # live LLM call path lives below, skipped during replay`}</code>
        </pre>

        <p>
          The only difference between live ingestion and replay is that one keyword
          argument. During live classification a cache miss falls through to the LLM.
          During replay a cache miss returns None and the candidate is logged as
          skipped. The response carries that skipped count so the UI can surface it
          honestly: seven candidates skipped, not yet classified at the time.
        </p>

        <h2 className="pt-4 text-xl font-semibold tracking-tight text-zinc-100">
          The two things that make this work
        </h2>

        <p>
          The cache is keyed on the inputs that fully determine the output. Same event,
          same parcel, same thesis version, same tier. Same answer, every time. The
          cache is not an optimization layer bolted onto a stochastic system. It is the
          system&apos;s function table. The LLM is how we populate it the first time and
          nothing more.
        </p>

        <p>
          The cache only mode is a hard wall. There is no fallback path during replay
          that calls the live API. This matters because vendor outages, model version
          changes, and prompt cache TTL behavior would all introduce nondeterminism if
          we let live calls back in. The slider has to give the same answer at noon and
          at midnight. That property is enforced by a single boolean argument flowing
          down through tier one and tier two.
        </p>

        <h2 className="pt-4 text-xl font-semibold tracking-tight text-zinc-100">
          What it lets you do
        </h2>

        <p>
          Drag a ninety day slider on the watchlist page and watch the alert feed
          redraw. The cache hit percentage in the provenance line tells you how much of
          the historical signal is recoverable. On the demo data set today, every
          previously classified event in the window comes back in single digit
          milliseconds.
        </p>

        <p>
          Edit a watchlist&apos;s thesis. The thesis_version increments. Every cache key
          that contained the old version is now in a separate namespace from the new
          one. Replay over the old thesis stays deterministic. Replay over the new
          thesis fills in lazily as the live ingest path runs against the new criterion.
          If a homebuilder pivots underwriting in March, they can compare the alert
          stream the old thesis would have surfaced against what the new one produces,
          on the same input events.
        </p>

        <p>
          Audit. Someone asks why a parcel was not alerted on March fourteenth. Replay a
          one day window. Inspect the skipped count and the materiality scores. The
          answer is in the response, not in someone&apos;s memory of what the prompt
          used to look like.
        </p>

        <h2 className="pt-4 text-xl font-semibold tracking-tight text-zinc-100">
          What we gave up
        </h2>

        <p>
          Replay reuses today&apos;s parcels projection, not a snapshot from the past.
          If a parcel rezoned between the event time and now, the replay sees the
          current zoning when constructing the materiality prompt. The honest fix is
          bitemporal projections, snapshotted at event ingest time. For a thirty day
          window over a county that doesn&apos;t rezone often, the parcel projection
          drifts slowly enough that this is acceptable. For a five year audit it is not.
          We named the limit in the README rather than pretending it does not exist.
        </p>

        <p>
          We also do not retroactively classify events that were never seen during live
          ingestion. If the watchlist was created on April tenth and the event happened
          on March first, that event is a permanent skip for that watchlist. The
          skipped count in the UI makes this visible: it would lie to silently drop
          them, and it would be wrong to fall through to a live LLM call that breaks
          determinism.
        </p>

        <p>
          Both are recoverable. Snapshot parcels on every event ingest. Allow replay to
          fall through to live calls when the cache misses, accepting the cost and the
          determinism loss. Neither pulls weight at the scale of one demo county and
          one demo watchlist. We sized the implementation for the property we actually
          need today, and named the v2 work in the README.
        </p>

        <h2 className="pt-4 text-xl font-semibold tracking-tight text-zinc-100">
          Try it
        </h2>

        <p>
          The slider is at{" "}
          <Link
            href="/w/00000000-0000-0000-0000-000000000001/replay"
            className="text-sky-400 hover:text-sky-300"
          >
            /w/00000000-0000-0000-0000-000000000001/replay
          </Link>
          . The provenance line under the handles updates on every drag. Source on
          GitHub at{" "}
          <a
            href="https://github.com/krish1236/parcelpulse"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sky-400 hover:text-sky-300"
          >
            krish1236/parcelpulse
          </a>
          .
        </p>
      </article>
    </main>
  );
}
