import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ConfirmDialog from "../components/ConfirmDialog";

/**
 * Asks before leaving a page with unsaved changes (forensics "Dokumentation" 1, IN-APP "no silent
 * data loss").
 *
 * The app uses `<BrowserRouter>`, not a data router, so react-router's `useBlocker` is not
 * available. Instead:
 *  - in-app links: a capture-phase click listener on the document sees the click before
 *    react-router's `<Link>` does; `preventDefault()` there makes the link skip its navigation, and
 *    the dialog navigates once the user confirms. That covers every `<a href>` in both shells
 *    (sidebar, bottom bar, tabs, chapter list).
 *  - reload, closing the tab, external links: the browser's own `beforeunload` prompt.
 * Programmatic navigation (Back button, ⌘K) is not intercepted; the draft is in sessionStorage
 * anyway (lib/drafts.ts), so coming back restores it -- the prompt is a courtesy, not the only
 * safeguard.
 *
 * Returns `[dialog, leave]`: render the dialog once in the page; call `leave(path)` instead of
 * `navigate(path)` for navigation the page itself starts (e.g. a chapter `<select>`), so it asks too.
 */
export function useLeaveGuard(dirty: boolean, what: string): [ReactNode, (to: string) => void] {
  const navigate = useNavigate();
  const location = useLocation();
  const [pending, setPending] = useState<string | null>(null);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const hereRef = useRef(location.pathname);
  hereRef.current = location.pathname;

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers only show the prompt when returnValue is set.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!dirtyRef.current || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; // new tab/window
      const anchor = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor || (anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return; // beforeunload handles leaving the app
      if (url.pathname === hereRef.current) return; // same page (e.g. a query change)
      event.preventDefault();
      setPending(url.pathname + url.search + url.hash);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  const leave = (to: string) => {
    if (dirtyRef.current) setPending(to);
    else navigate(to);
  };

  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      title="Ungespeicherte Änderungen"
      consequences={[
        <>Deine Änderungen an {what} sind noch nicht gespeichert.</>,
        <>Der Entwurf bleibt in diesem Browser-Tab erhalten; wenn du zurückkommst, ist er wieder da.</>,
      ]}
      confirmLabel="Trotzdem wechseln"
      cancelLabel="Hier bleiben"
      onConfirm={() => {
        const target = pending;
        setPending(null);
        if (target) navigate(target);
      }}
      onCancel={() => setPending(null)}
    />
  );
  return [dialog, leave];
}
