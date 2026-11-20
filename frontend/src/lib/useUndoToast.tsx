import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/**
 * "Erledigt -- Rückgängig" toast (forensics Q4). Two ways to use it:
 *
 *  - Deferred commit (for actions the backend cannot undo): pass `commit`. Nothing is sent until
 *    the toast runs out; "Rückgängig" just drops it. Showing a second toast, or leaving the page,
 *    commits the pending one first -- an action the user confirmed is never silently lost.
 *  - Real undo (the backend can reverse it): do the action first, pass `undo` to reverse it.
 *
 * Returns `[toastElement, show]`; render the element once anywhere in the page.
 */
export interface UndoToastOptions {
  message: string;
  /** Runs when the toast expires without "Rückgängig" (deferred commit). */
  commit?: () => void | Promise<void>;
  /** Runs when the user clicks "Rückgängig" (action already done). */
  undo?: () => void | Promise<void>;
  /** Milliseconds until the toast closes; default 8 s. */
  timeoutMs?: number;
}

export function useUndoToast(): [ReactNode, (options: UndoToastOptions) => void] {
  const [current, setCurrent] = useState<UndoToastOptions | null>(null);
  const pending = useRef<UndoToastOptions | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const settle = useCallback((undone: boolean) => {
    window.clearTimeout(timer.current);
    const item = pending.current;
    pending.current = null;
    setCurrent(null);
    if (!item) return;
    if (undone) void item.undo?.();
    else void item.commit?.();
  }, []);

  const show = useCallback((options: UndoToastOptions) => {
    if (pending.current) settle(false);
    pending.current = options;
    setCurrent(options);
    timer.current = window.setTimeout(() => settle(false), options.timeoutMs ?? 8000);
  }, [settle]);

  // Leaving the page commits what is pending instead of dropping it.
  useEffect(() => () => {
    window.clearTimeout(timer.current);
    const item = pending.current;
    pending.current = null;
    if (item) void item.commit?.();
  }, []);

  const element = current ? (
    <div className="undo-toast" role="status" aria-live="polite">
      <span>{current.message}</span>
      {(current.undo || current.commit) && (
        <button type="button" className="secondary small" onClick={() => settle(true)}>Rückgängig</button>
      )}
    </div>
  ) : null;

  return [element, show];
}
