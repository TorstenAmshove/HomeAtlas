import { createContext, useContext, useEffect } from "react";

/**
 * Lets a detail page put its own name into the top bar ("← Geräte / NAS"), so the page itself
 * needs no visible <h1> repeating it (forensics Q1). Provided by AppShell; outside the new shell
 * the default context makes `usePageTitle` a no-op.
 */
export const PageTitleContext = createContext<(title: string | null) => void>(() => {});

export function usePageTitle(title: string | null) {
  const setTitle = useContext(PageTitleContext);
  useEffect(() => {
    setTitle(title);
    return () => setTitle(null);
  }, [setTitle, title]);
}
