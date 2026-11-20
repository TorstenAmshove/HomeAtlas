/**
 * Unsaved drafts kept in `sessionStorage` (docs/redesign/5-information-architecture.md, "Zustand in
 * der URL": doc text, notes and chat input survive switching pages and reloads in this tab).
 *
 * sessionStorage on purpose, not localStorage: a draft belongs to the tab it was typed in and goes
 * away with it, so a half-typed text never shows up days later on another device user's screen
 * and never outlives the browser session on a shared computer.
 *
 * Every access is wrapped: storage can be unavailable (private mode, quota), and a draft that cannot
 * be kept must never break typing.
 */

const PREFIX = "homeatlas.draft.";

export function readDraft(key: string): string | null {
  try {
    return window.sessionStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

/** Stores the draft; `null` removes it. An empty string is kept (a deliberately emptied text is a draft too). */
export function writeDraft(key: string, value: string | null): void {
  try {
    if (value === null) window.sessionStorage.removeItem(PREFIX + key);
    else window.sessionStorage.setItem(PREFIX + key, value);
  } catch {
    // Storage full or blocked: the draft only lives in the page state then.
  }
}

/** Removes every draft of this tab. Called on logout: notes can hold locations or access hints,
 *  and on a shared computer they must not stay readable for the next person until the tab closes. */
export function clearAllDrafts(): void {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const key = window.sessionStorage.key(i);
      if (key?.startsWith(PREFIX)) keys.push(key);
    }
    keys.forEach((key) => window.sessionStorage.removeItem(key));
  } catch {
    // Storage blocked: nothing was stored either.
  }
}

/** Draft keys, in one place so pages can't drift apart. */
export const draftKeys = {
  docBody: (slug: string) => `doc.body.${slug}`,
  docManual: (slug: string) => `doc.manual.${slug}`,
  /** `updatedAt` of the chapter the body draft was started from, to warn when it changed since. */
  docBase: (slug: string) => `doc.base.${slug}`,
  /** `chatId` is "" for "no conversation yet" (the first message creates one). */
  chatInput: (chatId: string) => `chat.input.${chatId || "new"}`,
};
