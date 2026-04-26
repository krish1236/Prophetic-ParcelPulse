"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { addParcels, createWatchlist } from "@/lib/api";

export default function NewWatchlistPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [thesis, setThesis] = useState("");
  const [apnsText, setApnsText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<{
    added: number;
    not_found: number;
  } | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResolved(null);
    if (thesis.trim().length < 20) {
      setError("Deal thesis must be at least 20 characters.");
      return;
    }
    const apns = apnsText
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    setSubmitting(true);
    try {
      const wl = await createWatchlist({ name: name.trim(), deal_thesis: thesis.trim() });
      if (apns.length > 0) {
        const r = await addParcels(wl.watchlist_id, { apns });
        setResolved({ added: r.added, not_found: r.not_found });
        if (r.added === 0) {
          // Stay on page so user can correct or try polygon flow.
          setSubmitting(false);
          return;
        }
      }
      router.push(`/w/${wl.watchlist_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "create failed");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-10">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-zinc-500 transition hover:text-zinc-300"
      >
        ← back to home
      </Link>

      <header className="mt-6 mb-8 space-y-2">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
          New watchlist
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          Watch parcels you care about
        </h1>
        <p className="text-sm text-zinc-500">
          Name your watchlist, write the deal thesis in plain English, and add
          Multnomah County parcels by APN. ParcelPulse will monitor permits,
          zoning, FEMA, ownership, and listings against the thesis and surface
          ranked alerts.
        </p>
      </header>

      <form onSubmit={onSubmit} className="space-y-6">
        <Field label="Name" required>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={100}
            placeholder="e.g. Inner SE infill — Q3 sourcing"
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
        </Field>

        <Field
          label="Deal thesis"
          required
          help="Plain English, 20+ chars. Used by the materiality screen for every alert."
        >
          <textarea
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            required
            minLength={20}
            maxLength={2000}
            rows={4}
            placeholder="Townhomes 8-12 du/ac, must clear FEMA Zone X. Looking for infill or small-multifamily lots in central Portland."
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
          <p className="mt-1 text-right font-mono text-[11px] text-zinc-600">
            {thesis.length} / 2000
          </p>
        </Field>

        <Field
          label="Parcels"
          help="One Multnomah APN per line (or comma-separated). The polygon-draw flow lands in Phase 9 chunk 3."
        >
          <textarea
            value={apnsText}
            onChange={(e) => setApnsText(e.target.value)}
            rows={5}
            placeholder={`1S1E03CD  -00800\n1N1E35AB  -07101\n1N1E23DB  -15600`}
            className="w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 font-mono text-xs leading-relaxed text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none"
          />
        </Field>

        {error && (
          <p className="rounded-md border border-rose-900/40 bg-rose-950/30 px-3 py-2 font-mono text-xs text-rose-300">
            {error}
          </p>
        )}

        {resolved && resolved.added === 0 && (
          <p className="rounded-md border border-amber-900/40 bg-amber-950/30 px-3 py-2 font-mono text-xs text-amber-300">
            Watchlist created, but none of the {resolved.not_found} APNs matched
            a Multnomah parcel. Check the APN format (e.g.{" "}
            <code>1S1E03CD&nbsp;&nbsp;-00800</code>) or try the polygon flow.
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-sky-500 px-4 py-2 font-mono text-xs uppercase tracking-wider text-zinc-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "creating…" : "create watchlist"}
          </button>
          <Link
            href="/"
            className="font-mono text-xs uppercase tracking-wider text-zinc-500 transition hover:text-zinc-300"
          >
            cancel
          </Link>
        </div>
      </form>
    </main>
  );
}

function Field({
  label,
  help,
  required,
  children,
}: {
  label: string;
  help?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="font-mono text-xs uppercase tracking-wider text-zinc-500">
        {label}
        {required && <span className="ml-1 text-rose-400">*</span>}
      </span>
      {children}
      {help && <p className="font-mono text-[11px] text-zinc-600">{help}</p>}
    </label>
  );
}
