import type { KeyboardEvent } from "react";

import type { SingleSearchResult } from "../../api/types";

export interface ShownResult {
  result: SingleSearchResult;
  /** Rank in the response, 1-based, kept when results are collapsed or hidden. */
  rank: number;
  /** Lower-ranked results of the same shot folded into this one. */
  folded: number;
}

/**
 * Results without a shot (videos with no scene split, e.g. group S) fall back to 10-second
 * windows of their video: organiser keyframes are a few seconds apart, so a narrower window
 * would rarely fold anything.
 */
const FALLBACK_WINDOW_MS = 10_000;
const FALLBACK_FPS = 25;

function shotKey(result: SingleSearchResult): string {
  if (result.segment_id) return `${result.video_id}|${result.segment_id}`;
  const ms = result.time_ms ?? (result.frame_id / FALLBACK_FPS) * 1000;
  return `${result.video_id}|t${Math.floor(ms / FALLBACK_WINDOW_MS)}`;
}

/**
 * Results in rank order; with ``collapse`` only the best result of each shot stays, counting
 * the others in ``folded`` (adjacent frames of one shot are usually the same moment).
 */
export function shownResults(
  results: readonly SingleSearchResult[],
  { collapse, hiddenVideos }: { collapse: boolean; hiddenVideos: ReadonlySet<string> },
): ShownResult[] {
  const shown: ShownResult[] = [];
  const byShot = new Map<string, ShownResult>();
  results.forEach((result, index) => {
    if (hiddenVideos.has(result.video_id)) return;
    if (!collapse) {
      shown.push({ result, rank: index + 1, folded: 0 });
      return;
    }
    const key = shotKey(result);
    const kept = byShot.get(key);
    if (kept) {
      kept.folded += 1;
      return;
    }
    const entry = { result, rank: index + 1, folded: 0 };
    byShot.set(key, entry);
    shown.push(entry);
  });
  return shown;
}

/**
 * Arrow keys move the focus between the frames of a grid (Home / End to the first / last).
 * The number of columns is read from the layout, so it follows the window and the density.
 */
export function moveFocusInGrid(event: KeyboardEvent<HTMLElement>, itemSelector: string) {
  const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
  if (!keys.includes(event.key) || event.altKey || event.ctrlKey || event.metaKey) return;
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(itemSelector));
  const current = items.indexOf(document.activeElement as HTMLElement);
  if (current < 0) return;

  // The first item placed lower than the first one starts the second row.
  const firstTop = items[0]?.getBoundingClientRect().top ?? 0;
  const secondRow = items.findIndex((item) => item.getBoundingClientRect().top > firstTop + 1);
  const perRow = secondRow === -1 ? items.length : secondRow;
  const target = {
    ArrowLeft: current - 1,
    ArrowRight: current + 1,
    ArrowUp: current - perRow,
    ArrowDown: current + perRow,
    Home: 0,
    End: items.length - 1,
  }[event.key as "Home"];
  const next = items[Math.min(Math.max(target, 0), items.length - 1)];
  if (!next || next === items[current]) return;
  event.preventDefault();
  // Focusing scrolls the frame into view.
  next.focus();
}
