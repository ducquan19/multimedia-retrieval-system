import { useSyncExternalStore } from "react";

import type { SubmitMode } from "./DresSubmitPanel";

const STORAGE_KEY = "aic-dres-log";
const CHANGE_EVENT = "aic-dres-log-change";
const MAX_ENTRIES = 200;

export interface SubmissionLogEntry {
  at: number;
  evaluationId: string;
  mode: SubmitMode;
  videoId: string;
  /** What was sent: the time range, or the answer text. */
  answer: string;
  /** DRES verdict (e.g. CORRECT / WRONG), or a short error. */
  verdict: string;
  /** True only for a CORRECT verdict. */
  ok: boolean;
  /** Absent on entries logged before tones existed; derive it from `ok`. */
  tone?: SubmissionTone;
  /** DRES answered with 2xx, so the backend will refuse this exact answer again. */
  judged?: boolean;
}

export type SubmissionTone = "ok" | "fail" | "pending";

export function entryTone(entry: SubmissionLogEntry): SubmissionTone {
  return entry.tone ?? (entry.ok ? "ok" : "fail");
}

let cachedRaw: string | null = null;
let cachedEntries: SubmissionLogEntry[] = [];

export function readSubmissionLog(): SubmissionLogEntry[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Storage unavailable: the log is simply empty.
  }
  if (raw === cachedRaw) return cachedEntries;
  cachedRaw = raw;
  try {
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    cachedEntries = Array.isArray(parsed) ? (parsed as SubmissionLogEntry[]) : [];
  } catch {
    cachedEntries = [];
  }
  return cachedEntries;
}

function writeSubmissionLog(entries: SubmissionLogEntry[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // The submission itself already happened; losing the local log is acceptable.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function appendSubmissionLog(entry: SubmissionLogEntry) {
  writeSubmissionLog([entry, ...readSubmissionLog()]);
}

export function clearSubmissionLog() {
  writeSubmissionLog([]);
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange);
  // Another tab submitting updates this one too.
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** Newest first. */
export function useSubmissionLog(): SubmissionLogEntry[] {
  return useSyncExternalStore(subscribe, readSubmissionLog, readSubmissionLog);
}

export function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("vi-VN", { hour12: false });
}
