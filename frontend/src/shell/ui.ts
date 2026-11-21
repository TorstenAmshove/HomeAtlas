import { createContext, useContext } from "react";
import type { ThemeMode } from "./prefs";

/** UI preferences held by App.tsx; pages read them through `useUi()` (settings: "Darstellung"). */
export interface UiState {
  themeMode: ThemeMode;
  setThemeMode: (value: ThemeMode) => void;
}

export const UiContext = createContext<UiState>({
  themeMode: "system",
  setThemeMode: () => {},
});

export const useUi = () => useContext(UiContext);
