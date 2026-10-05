import { useEffect, useState } from "react";

const DARK_MODE_STORAGE_KEY = "aic-retrieval-theme";

function prefersDarkMode(): boolean {
  try {
    const storedTheme = window.localStorage.getItem(DARK_MODE_STORAGE_KEY);
    if (storedTheme === "dark") return true;
    if (storedTheme === "light") return false;
  } catch {
    // Fall through to the operating-system preference when storage is unavailable.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

/** Dark-mode switch persisted per browser and applied as <html data-theme>. */
export function useThemePreference(): [boolean, (dark: boolean) => void] {
  const [isDarkMode, setIsDarkMode] = useState(prefersDarkMode);

  useEffect(() => {
    const theme = isDarkMode ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(DARK_MODE_STORAGE_KEY, theme);
    } catch {
      // The visual preference still applies for this session when storage is unavailable.
    }
  }, [isDarkMode]);

  return [isDarkMode, setIsDarkMode];
}
