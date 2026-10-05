/** "ALL" or a key returned by programOf. */
export type ProgramFilter = string;

const PROGRAM_LABELS: Record<string, string> = {
  NEWS: "Tin tức",
  CYCLING: "Đua xe đạp",
  TRAFFIC: "Camera giao thông",
  L24: "Múa lân",
  L25: "Ôn thi THPT",
  L26: "Món ngon mỗi ngày",
};

/** Program keys by video prefix; the same content from batch 1 and batch 2 shares one key. */
const PROGRAM_BY_PREFIX: Record<string, string> = {
  L21: "NEWS",
  L22: "NEWS",
  M: "NEWS",
  L23: "CYCLING",
  S: "CYCLING",
  N: "TRAFFIC",
};

/** L videos group by program code; batch 2 by collection letter (M01_V001 -> M). */
export function programOf(videoId: string): string {
  const prefix = videoId.split(/[_-]/, 1)[0] ?? videoId;
  const code = prefix.startsWith("L") ? prefix : prefix.charAt(0);
  return PROGRAM_BY_PREFIX[code] ?? code;
}

export function matchesProgram(videoId: string, program: ProgramFilter): boolean {
  return program === "ALL" || programOf(videoId) === program;
}

export function programOptions(
  videoIds: string[],
  selected: ProgramFilter,
): { key: string; label: string }[] {
  const counts = new Map<string, number>();
  for (const videoId of videoIds) {
    const program = programOf(videoId);
    counts.set(program, (counts.get(program) ?? 0) + 1);
  }
  // Keep the current choice listed so a new search does not silently drop it.
  if (selected !== "ALL" && !counts.has(selected)) counts.set(selected, 0);
  return Array.from(counts, ([key, count]) => ({
    key,
    label: `${PROGRAM_LABELS[key] ?? key} (${count})`,
  })).sort((left, right) => left.label.localeCompare(right.label, "vi"));
}
