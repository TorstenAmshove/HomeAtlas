import { useEffect, useId, useRef, useState } from "react";

/**
 * The "⋯" button with rarely used or expensive actions behind it (forensics "Dokumentation" 2:
 * "Alles neu erzeugen" moves out of the page header). Closes on Esc, on a click outside and after
 * an item was chosen; focus returns to the button.
 */
export interface OverflowItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
}

export default function OverflowMenu({ items, label = "Weitere Aktionen" }: { items: OverflowItem[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    rootRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus();
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        buttonRef.current?.focus();
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const entries = Array.from(rootRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []);
        if (entries.length === 0) return;
        event.preventDefault();
        const index = entries.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === "ArrowDown" ? index + 1 : index - 1;
        entries[(next + entries.length) % entries.length].focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="overflow-menu" ref={rootRef}>
      <button ref={buttonRef} type="button" className="secondary small overflow-menu-button" aria-label={label}
              title={label} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
              onClick={() => setOpen((v) => !v)}>
        ⋯
      </button>
      {open && (
        <div className="overflow-menu-list" role="menu" id={menuId}>
          {items.map((item) => (
            <button key={item.label} type="button" role="menuitem" disabled={item.disabled}
                    className={`sbtn overflow-menu-item${item.danger ? " danger" : ""}`}
                    onClick={() => { setOpen(false); buttonRef.current?.focus(); item.onSelect(); }}>
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
