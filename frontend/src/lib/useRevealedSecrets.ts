import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** How long a revealed password stays on screen (forensics "Gerät" 8, same as the device page). */
export const SECRET_VISIBLE_MS = 30_000;

/**
 * Passwords revealed one at a time through the existing admin-only `GET /api/accounts/{id}/secret`
 * (which writes a `secret.reveal` entry to the access log). Each hides itself again after 30 s, so
 * a revealed secret does not stay readable on a screen someone walked away from. Kept only in this
 * hook's state: never in storage, never in the URL. Unmounting drops them.
 */
export function useRevealedSecrets(): {
  secrets: Record<string, string>;
  reveal: (accountId: string) => Promise<void>;
  hide: (accountId: string) => void;
} {
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const timers = useRef<Record<string, number>>({});

  const mounted = useRef(false);

  useEffect(() => {
    // Set in the effect body (not only initialised) so StrictMode's setup -> cleanup -> setup works.
    mounted.current = true;
    const pending = timers.current;
    return () => {
      mounted.current = false;
      Object.values(pending).forEach((t) => window.clearTimeout(t));
    };
  }, []);

  const hide = useCallback((accountId: string) => {
    window.clearTimeout(timers.current[accountId]);
    delete timers.current[accountId];
    setSecrets((current) => {
      if (!(accountId in current)) return current;
      const next = { ...current };
      delete next[accountId];
      return next;
    });
  }, []);

  const reveal = useCallback(async (accountId: string) => {
    const { secret } = await api.revealSecret(accountId);
    if (!mounted.current) return; // unmounted while waiting: no state, no timer
    setSecrets((current) => ({ ...current, [accountId]: secret }));
    window.clearTimeout(timers.current[accountId]);
    timers.current[accountId] = window.setTimeout(() => hide(accountId), SECRET_VISIBLE_MS);
  }, [hide]);

  return { secrets, reveal, hide };
}
