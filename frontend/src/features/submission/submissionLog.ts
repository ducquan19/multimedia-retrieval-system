import { useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";

import { getDresSubmissions } from "../../api/client";
import type { DresSubmissionRecord, DresSubmitResponse } from "../../api/types";

/**
 * Submission log shown next to the DRES panel.
 *
 * Answers DRES judged come from the backend (GET /api/dres/submissions): its log survives a
 * cleared browser and is what the duplicate guard checks. Attempts that never got a verdict
 * (network error, DRES rejected the request) are only known to this browser, so they are kept
 * in localStorage and can be cleared.
 */

export type SubmitMode = "KIS" | "VQA" | "TRAKE";

const STORAGE_KEY = "aic-dres-log";
const CHANGE_EVENT = "aic-dres-log-change";
const MAX_ENTRIES = 200;
export const SUBMISSIONS_QUERY_KEY = ["dres-submissions"] as const;

export interface SubmissionLogEntry {
  at: number;
  evaluationId: string;
  /** Null for a judged answer whose text the backend could not attribute to a mode. */
  mode: SubmitMode | null;
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

type Verdict = Pick<DresSubmitResponse, "accepted" | "submission" | "description">;

/**
 * Colour of a DRES reply: green only for a CORRECT verdict, red for WRONG or a
 * rejection, amber while DRES has not judged it (INDETERMINATE / no verdict).
 */
export function submissionTone(response: Verdict): SubmissionTone {
  if (!response.accepted) return "fail";
  const text = `${response.submission ?? ""} ${response.description ?? ""}`;
  if (/\b(WRONG|INCORRECT)\b/i.test(text)) return "fail";
  if (/\bCORRECT\b/i.test(text)) return "ok";
  return "pending";
}

export function verdictLabel(response: Verdict): string {
  return response.submission ?? (response.accepted ? "Đã nộp, chờ chấm" : "Nộp thất bại");
}

export function entryTone(entry: SubmissionLogEntry): SubmissionTone {
  return entry.tone ?? (entry.ok ? "ok" : "fail");
}

function fromRecord(record: DresSubmissionRecord): SubmissionLogEntry {
  const tone = submissionTone(record);
  return {
    at: Date.parse(record.time),
    evaluationId: record.evaluation_id,
    mode: record.mode,
    videoId: record.video_id ?? "",
    answer: record.answer,
    verdict: verdictLabel(record),
    ok: tone === "ok",
    tone,
    judged: true,
  };
}

let cachedRaw: string | null = null;
let cachedEntries: SubmissionLogEntry[] = [];

/** Attempts without a verdict, newest first (judged entries of older versions are dropped). */
export function readLocalAttempts(): SubmissionLogEntry[] {
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
    cachedEntries = Array.isArray(parsed)
      ? (parsed as SubmissionLogEntry[]).filter((entry) => entry.judged !== true)
      : [];
  } catch {
    cachedEntries = [];
  }
  return cachedEntries;
}

function writeLocalAttempts(entries: SubmissionLogEntry[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX_ENTRIES)));
  } catch {
    // The attempt itself already happened; losing the local note is acceptable.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Remember an attempt DRES did not judge; judged answers are in the backend log. */
export function appendLocalAttempt(entry: SubmissionLogEntry) {
  writeLocalAttempts([entry, ...readLocalAttempts()]);
}

export function clearLocalAttempts() {
  writeLocalAttempts([]);
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

export interface SubmissionHistory {
  /** Judged answers and local attempts, newest first. */
  entries: SubmissionLogEntry[];
  localAttempts: number;
  /** The backend log could not be read (the judged answers are then missing). */
  historyUnavailable: boolean;
}

export function useSubmissionHistory(): SubmissionHistory {
  const local = useSyncExternalStore(subscribe, readLocalAttempts, readLocalAttempts);
  const judged = useQuery({
    queryKey: SUBMISSIONS_QUERY_KEY,
    queryFn: ({ signal }) => getDresSubmissions(signal),
    staleTime: 10_000,
  });
  const entries = [...(judged.data ?? []).map(fromRecord), ...local].sort((a, b) => b.at - a.at);
  return { entries, localAttempts: local.length, historyUnavailable: judged.isError };
}

export function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("vi-VN", { hour12: false });
}
