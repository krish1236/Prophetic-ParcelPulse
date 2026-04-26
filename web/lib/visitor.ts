"use client";

/**
 * Tracks watchlists this browser created so the landing page can resurface
 * them. Lives in localStorage — visitor-scoped, not signed; the data is
 * just public UUIDs the visitor already owns. Capped at 5 entries.
 */

const KEY = "pp_recent_watchlists";
const MAX = 5;

export type RecentWatchlist = {
  watchlist_id: string;
  name: string;
  created_at: string;
};

export function getRecentWatchlists(): RecentWatchlist[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.slice(0, MAX) : [];
  } catch {
    return [];
  }
}

export function rememberWatchlist(w: RecentWatchlist): void {
  if (typeof window === "undefined") return;
  const existing = getRecentWatchlists().filter(
    (x) => x.watchlist_id !== w.watchlist_id,
  );
  const updated = [w, ...existing].slice(0, MAX);
  localStorage.setItem(KEY, JSON.stringify(updated));
}
