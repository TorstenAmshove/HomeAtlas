import type { ReactNode } from "react";

/** Small building blocks shared by the tabs of the device page. */

export type Notice = { kind: "ok" | "error" | "info"; text: string } | null;

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function clock(d: Date) {
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

/** "heute 03:00", "gestern 22:15", "18.11., 07:42" (plus year when it is not this year). Same
 *  wording as the Start page. */
export function when(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  if (sameDay(d, now)) return `heute ${clock(d)}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(d, yesterday)) return `gestern ${clock(d)}`;
  const date = d.toLocaleDateString("de-DE", {
    day: "2-digit", month: "2-digit", ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${date}, ${clock(d)}`;
}

export function fullDate(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("de-DE");
}

export function Section({ title, aside, children, id }: { title: string; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="dv-section" aria-labelledby={id}>
      <div className="dv-section-head">
        <h2 className="dv-sec" id={id}>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function NoticeLine({ notice }: { notice: Notice }) {
  if (!notice) return null;
  return <div className={`notice ${notice.kind}`} role="status">{notice.text}</div>;
}

/** Label/value rows (Steckbrief, Technische Daten …); empty values are left out. */
export function Facts({ rows, mono = false }: { rows: [string, ReactNode][]; mono?: boolean }) {
  const shown = rows.filter(([, value]) => value !== "" && value !== null && value !== undefined && value !== false);
  if (shown.length === 0) return null;
  return (
    <dl className="dv-facts">
      {shown.map(([label, value]) => (
        <div key={label} className="dv-fact">
          <dt>{label}</dt>
          <dd className={mono ? "mono" : undefined}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Log or config text: full width, scrolls inside itself. */
export function LogBox({ children, label }: { children: ReactNode; label: string }) {
  return <pre className="dv-log mono" tabIndex={0} aria-label={label}>{children}</pre>;
}

export function StateChip({ tone, children, title }: { tone: "ok" | "bad" | "warn" | ""; children: ReactNode; title?: string }) {
  return (
    <span className={`dv-chip${tone ? ` ${tone}` : ""}`} title={title}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  );
}
