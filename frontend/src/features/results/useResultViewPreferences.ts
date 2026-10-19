import { useState } from "react";

/** How many frames a row of the contact sheet holds: small frames show more results at once. */
export type FrameSize = "S" | "M" | "L";

export interface ResultViewPreferences {
  frameSize: FrameSize;
  collapseShots: boolean;
}

const STORAGE_KEY = "aic-result-view";
const DEFAULTS: ResultViewPreferences = { frameSize: "M", collapseShots: false };

function read(): ResultViewPreferences {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object") return DEFAULTS;
    const stored = parsed as Partial<ResultViewPreferences>;
    return {
      frameSize: stored.frameSize === "S" || stored.frameSize === "L" ? stored.frameSize : "M",
      collapseShots: stored.collapseShots === true,
    };
  } catch {
    return DEFAULTS;
  }
}

/** Frame size and shot collapsing, remembered in this browser. */
export function useResultViewPreferences() {
  const [preferences, setPreferences] = useState<ResultViewPreferences>(read);
  const update = (change: Partial<ResultViewPreferences>) => {
    setPreferences((current) => {
      const next = { ...current, ...change };
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        // The preference still applies until the page is reloaded.
      }
      return next;
    });
  };
  return [preferences, update] as const;
}
