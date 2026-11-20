import { useEffect, useRef, type ReactNode } from "react";

/**
 * Review step before a dangerous action (forensics Q4: replaces `window.confirm` in new code).
 * It says in plain words what will happen -- `consequences` is a short list such as "Das Gerät
 * „NAS“ wird gelöscht" / "3 Zugänge verlieren ihre Zuordnung" -- and names the action on the
 * button ("Gerät löschen", not "OK"). Cancel is focused first and Esc cancels, so a stray Enter
 * never confirms.
 *
 * Usage: keep `open` in state, run the action in `onConfirm` (may be async; the buttons are
 * disabled while it runs) and close the dialog when it resolves.
 */
export default function ConfirmDialog({
  open, title, consequences, children, confirmLabel, cancelLabel = "Abbrechen", danger = false,
  busy = false, onConfirm, onCancel,
}: {
  open: boolean;
  title: string;
  /** What will happen, one plain sentence each. */
  consequences?: ReactNode[];
  /** Extra explanation below the list (e.g. "Das lässt sich nicht rückgängig machen."). */
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
           aria-describedby="confirm-body">
        <h2 id="confirm-title">{title}</h2>
        <div id="confirm-body">
          {consequences && consequences.length > 0 && (
            <>
              <p className="dialog-lead">Wenn du bestätigst:</p>
              <ul className="dialog-consequences">
                {consequences.map((item, i) => <li key={i}>{item}</li>)}
              </ul>
            </>
          )}
          {children}
        </div>
        <div className="dialog-actions">
          <button ref={cancelRef} type="button" className="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" className={danger ? "danger-solid" : ""} onClick={() => void onConfirm()} disabled={busy}>
            {busy ? "Bitte warten …" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
