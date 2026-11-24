import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * One piece of page state kept in the URL's query string (docs/redesign/5-information-architecture.md,
 * "Zustand in der URL"), so Back, reload and a shared link land exactly where the user was.
 *
 * The default value is never written: `?tab=` disappears when the tab is back at its default.
 * Updates replace the history entry by default (typing into a filter must not create one entry per
 * key stroke); pass `{ push: true }` for changes that should be their own Back step. (Tabs do not: they replace the
 * entry, so Back leaves the page in one step.)
 */
export function useUrlState(
  key: string,
  defaultValue = "",
): [string, (value: string, options?: { push?: boolean }) => void] {
  const [params, setParams] = useSearchParams();
  const value = params.get(key) ?? defaultValue;

  const setValue = useCallback((next: string, options?: { push?: boolean }) => {
    setParams((current) => {
      const updated = new URLSearchParams(current);
      if (next === defaultValue) updated.delete(key);
      else updated.set(key, next);
      return updated;
    }, { replace: !options?.push });
  }, [key, defaultValue, setParams]);

  return [value, setValue];
}
