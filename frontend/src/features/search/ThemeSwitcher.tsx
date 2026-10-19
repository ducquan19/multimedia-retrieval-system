import type { ReactNode } from "react";

import type { ThemeMode } from "./useThemePreference";

// Lucide icons (ISC licence): stroke drawings that follow the text colour.
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const MODES: Record<ThemeMode, { label: string; next: ThemeMode; icon: ReactNode }> = {
  light: {
    label: "sáng",
    next: "dark",
    icon: (
      <Icon>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </Icon>
    ),
  },
  dark: {
    label: "tối",
    next: "system",
    icon: (
      <Icon>
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
      </Icon>
    ),
  },
  system: {
    label: "theo thiết bị",
    next: "light",
    icon: (
      <Icon>
        <rect width="20" height="14" x="2" y="3" rx="2" />
        <path d="M8 21h8M12 17v4" />
      </Icon>
    ),
  },
};

interface ThemeSwitcherProps {
  mode: ThemeMode;
  onChange: (mode: ThemeMode) => void;
}

/** One button showing the current theme; each press moves to light, dark or the device's. */
export function ThemeSwitcher({ mode, onChange }: ThemeSwitcherProps) {
  const { label, next, icon } = MODES[mode];
  const description = `Giao diện ${label}. Bấm để chuyển sang ${MODES[next].label}`;
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => onChange(next)}
      aria-label={description}
      title={description}
    >
      {icon}
    </button>
  );
}
