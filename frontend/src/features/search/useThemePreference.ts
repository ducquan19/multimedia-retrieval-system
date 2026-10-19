import { useEffect, useState } from "react";

const THEME_STORAGE_KEY = "aic-retrieval-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

/** "system" follows the operating system, also when it changes while the page is open. */
export type ThemeMode = "light" | "dark" | "system";

function storedMode(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Storage unavailable: follow the operating system.
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return window.matchMedia?.(DARK_QUERY).matches ?? false;
}

/** Theme choice persisted per browser and applied as <html data-theme="light|dark">. */
export function useThemePreference(): [ThemeMode, (mode: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(storedMode);

  useEffect(() => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, mode);
    } catch {
      // The theme still applies for this session when storage is unavailable.
    }
    const apply = () => {
      const dark = mode === "dark" || (mode === "system" && systemPrefersDark());
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    if (mode !== "system" || !window.matchMedia) return;
    const query = window.matchMedia(DARK_QUERY);
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, [mode]);

  return [mode, setMode];
}
