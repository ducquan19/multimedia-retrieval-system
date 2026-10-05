import type { SearchRequest, SearchResponse } from "../../api/types";

export interface CachedSearch {
  payload: SearchRequest;
  response: SearchResponse;
  /** When the backend answered (ms since epoch). */
  at: number;
}

/** JSON with sorted object keys, so equal requests give equal keys whatever the field order. */
export function requestKey(payload: SearchRequest): string {
  return JSON.stringify(payload, (_, value: unknown) =>
    value && typeof value === "object" && !Array.isArray(value)
      ? Object.fromEntries(
          Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)),
        )
      : value,
  );
}

/**
 * Results of the searches run in this page session, most recent first, at most `limit` of them.
 * It lives in memory only: reloading the page (e.g. after rebuilding the indexes) starts empty,
 * so an old result can never outlive the data it came from.
 */
export class SearchResultCache {
  private readonly entries = new Map<string, CachedSearch>();

  constructor(private readonly limit = 30) {}

  has(payload: SearchRequest): boolean {
    return this.entries.has(requestKey(payload));
  }

  get(payload: SearchRequest): CachedSearch | undefined {
    const key = requestKey(payload);
    const entry = this.entries.get(key);
    if (entry) {
      // Re-insert to mark it as recently used.
      this.entries.delete(key);
      this.entries.set(key, entry);
    }
    return entry;
  }

  put(entry: CachedSearch): void {
    const key = requestKey(entry.payload);
    this.entries.delete(key);
    this.entries.set(key, entry);
    while (this.entries.size > this.limit) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
  }
}
