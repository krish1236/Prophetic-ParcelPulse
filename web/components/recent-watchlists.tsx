"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { type RecentWatchlist, getRecentWatchlists } from "@/lib/visitor";

export function RecentWatchlists() {
  const [items, setItems] = useState<RecentWatchlist[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setItems(getRecentWatchlists());
    setHydrated(true);
  }, []);

  if (!hydrated || items.length === 0) return null;

  return (
    <section className="mt-12">
      <h2 className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
        Your recent watchlists
      </h2>
      <ul className="divide-y divide-zinc-900 rounded-lg border border-zinc-800 bg-zinc-950/50">
        {items.map((w) => (
          <li key={w.watchlist_id}>
            <Link
              href={`/w/${w.watchlist_id}`}
              className="flex items-center justify-between gap-3 px-4 py-3 transition hover:bg-zinc-900/50"
            >
              <span className="truncate text-sm text-zinc-200">{w.name}</span>
              <span className="shrink-0 font-mono text-[11px] text-zinc-500">
                {new Date(w.created_at).toLocaleDateString()}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
