import { useState } from "react";

import type { QueryType } from "../../api/types";

const STORAGE_KEY = "aic-query-history";
const MAX_PER_TYPE = 30;

export type QueryHistoryEntry =
  | { type: "KIS"; at: number; query: string }
  | { type: "TRAFFIC"; at: number; query: string }
  | { type: "TRAKE"; at: number; mainQuery: string; events: string[] };

function readHistory(): QueryHistoryEntry[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as QueryHistoryEntry[]) : [];
  } catch {
    return [];
  }
}

function entryKey(entry: QueryHistoryEntry): string {
  return entry.type === "TRAKE"
    ? `${entry.type}|${entry.mainQuery}|${entry.events.join("|")}`
    : `${entry.type}|${entry.query}`;
}

export function entryLabel(entry: QueryHistoryEntry): string {
  const text =
    entry.type === "TRAKE"
      ? [entry.mainQuery, ...entry.events].filter(Boolean).join(" → ")
      : entry.query;
  return text.length > 90 ? `${text.slice(0, 89)}…` : text;
}

/** Newest first; re-running a query moves it back to the top instead of duplicating it. */
export function useQueryHistory() {
  const [entries, setEntries] = useState(readHistory);

  const record = (entry: QueryHistoryEntry) => {
    const key = entryKey(entry);
    const others = readHistory().filter((item) => entryKey(item) !== key);
    const sameType = others.filter((item) => item.type === entry.type).slice(0, MAX_PER_TYPE - 1);
    const next = [entry, ...sameType, ...others.filter((item) => item.type !== entry.type)];
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // History is a convenience; the search itself does not depend on it.
    }
    setEntries(next);
  };

  return { entries, record };
}

interface QueryHistorySelectProps {
  type: QueryType;
  entries: QueryHistoryEntry[];
  onRestore: (entry: QueryHistoryEntry) => void;
}

export function QueryHistorySelect({ type, entries, onRestore }: QueryHistorySelectProps) {
  const forType = entries.filter((entry) => entry.type === type);
  if (forType.length === 0) return null;

  return (
    <select
      className="query-history"
      aria-label="Lịch sử truy vấn"
      value=""
      onChange={(event) => {
        const entry = forType[Number(event.target.value)];
        if (entry) onRestore(entry);
      }}
    >
      <option value="">Lịch sử truy vấn ({forType.length})</option>
      {forType.map((entry, index) => (
        <option key={`${entry.at}-${index}`} value={index}>
          {entryLabel(entry)}
        </option>
      ))}
    </select>
  );
}
