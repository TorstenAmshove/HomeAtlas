import { createContext, useContext } from "react";
import type { ThemeMode, UiOverride } from "./prefs";

/**
 * Which shell is showing and why. Held by App.tsx next to the auth state; pages read it through
 * `useUi()` (e.g. the settings page's "Neue Oberfläche" switch and "Darstellung" section).
 */
export interface UiState {
  /** The new shell is rendered (server flag, unless this browser overrides it). */
  calm: boolean;
  /** The instance-wide `uiCalm` flag as /api/health reported it. */
  serverCalm: boolean;
  setServerCalm: (value: boolean) => void;
  /** This browser's `?ui=` override, null = follow the server flag. */
  override: UiOverride;
  setOverride: (value: UiOverride) => void;
  themeMode: ThemeMode;
  setThemeMode: (value: ThemeMode) => void;
}

export const UiContext = createContext<UiState>({
  calm: false,
  serverCalm: false,
  setServerCalm: () => {},
  override: null,
  setOverride: () => {},
  themeMode: "system",
  setThemeMode: () => {},
});

export const useUi = () => useContext(UiContext);
