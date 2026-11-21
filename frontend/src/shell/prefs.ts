/**
 * Per-browser UI preferences (docs/redesign/5-information-architecture.md, "Design-Tokens und
 * Dunkelmodus"). Plain localStorage, never sent to the server:
 *
 *  - `theme`: "system" | "light" | "dark", the colour mode.
 *
 * Every access is wrapped: storage can be unavailable (private mode, blocked cookies), and a missing
 * preference must never break rendering.
 */

export type ThemeMode = "system" | "light" | "dark";

const KEY_THEME = "homeatlas.theme";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the preference just doesn't stick */
  }
}

/** Removes the keys of the old-UI switch (`ui`, `uiServer`). Can go once every browser has loaded
 *  the app once after this change. */
export function removeLegacyUiKeys(): void {
  write("homeatlas.ui", null);
  write("homeatlas.uiServer", null);
}

export function getThemeMode(): ThemeMode {
  const value = read(KEY_THEME);
  return value === "light" || value === "dark" ? value : "system";
}

export function setThemeModePref(value: ThemeMode): void {
  write(KEY_THEME, value === "system" ? null : value);
}
