/**
 * Per-browser UI preferences for the redesign (docs/redesign/5-information-architecture.md,
 * "Schalter" and "Design-Tokens und Dunkelmodus"). Plain localStorage, never sent to the server:
 *
 *  - `ui`: "calm" | "classic" overrides the instance-wide `uiCalm` flag for this browser only, so the
 *    new shell can be tried on one phone without switching it on for everyone. Set by visiting any
 *    page with `?ui=calm` / `?ui=classic` (the parameter is then removed from the address bar).
 *  - `uiServer`: the last `uiCalm` value /api/health returned. Only used to pick the loading screen
 *    before health has answered; the real decision always waits for health.
 *  - `theme`: "system" | "light" | "dark", the new shell's colour mode. The old UI ignores it.
 *
 * Every access is wrapped: storage can be unavailable (private mode, blocked cookies), and a missing
 * preference must never break rendering.
 */

export type UiOverride = "calm" | "classic" | null;
export type ThemeMode = "system" | "light" | "dark";

const KEY_UI = "homeatlas.ui";
const KEY_UI_SERVER = "homeatlas.uiServer";
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

/** Reads `?ui=` once at start-up, stores it, and drops it from the address bar. */
export function consumeUiQueryParam(): void {
  const url = new URL(window.location.href);
  const value = url.searchParams.get("ui");
  if (value !== "calm" && value !== "classic") return;
  write(KEY_UI, value);
  url.searchParams.delete("ui");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

export function getUiOverride(): UiOverride {
  const value = read(KEY_UI);
  return value === "calm" || value === "classic" ? value : null;
}

export function setUiOverride(value: UiOverride): void {
  write(KEY_UI, value);
}

export function getLastServerCalm(): boolean {
  return read(KEY_UI_SERVER) === "1";
}

export function setLastServerCalm(value: boolean): void {
  write(KEY_UI_SERVER, value ? "1" : "0");
}

export function resolveCalm(serverCalm: boolean, override: UiOverride): boolean {
  return override === null ? serverCalm : override === "calm";
}

export function getThemeMode(): ThemeMode {
  const value = read(KEY_THEME);
  return value === "light" || value === "dark" ? value : "system";
}

export function setThemeModePref(value: ThemeMode): void {
  write(KEY_THEME, value === "system" ? null : value);
}
