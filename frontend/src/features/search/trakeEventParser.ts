// "E1: ...", "E 2 - ...", "Event 3) ...", "e4. ..." at the start of a line.
const EVENT_MARKER = /^\s*(?:e|event)\s*(\d+)\s*[:.)\-–]\s*/i;

export interface ParsedTrakeEvents {
  /** Text before the first event marker, if any. */
  mainQuery: string;
  /** Event texts in E1..En order; a missing number leaves an empty slot. */
  events: string[];
}

/**
 * Parse a pasted multi-event TRAKE query. Returns null when the text has no
 * event marker, so ordinary pastes are left untouched.
 */
export function parseTrakeEvents(text: string): ParsedTrakeEvents | null {
  const preamble: string[] = [];
  const byNumber = new Map<number, string[]>();
  let current: string[] | null = null;

  for (const line of text.split(/\r?\n/)) {
    const marker = EVENT_MARKER.exec(line);
    if (marker) {
      const number = Number(marker[1]);
      if (number < 1) continue;
      current = byNumber.get(number) ?? [];
      byNumber.set(number, current);
      current.push(line.slice(marker[0].length));
    } else if (current) {
      // A line without a marker continues the previous event.
      current.push(line);
    } else {
      preamble.push(line);
    }
  }

  if (byNumber.size === 0) return null;

  const count = Math.max(...byNumber.keys());
  const join = (lines: string[]) => lines.map((line) => line.trim()).filter(Boolean).join(" ");
  return {
    mainQuery: join(preamble),
    events: Array.from({ length: count }, (_, index) => join(byNumber.get(index + 1) ?? [])),
  };
}
