import type { MonitorState } from "./api";

/** Short German time phrases shared by the Start page and the Netzplan, so both say it the same way. */

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function clock(d: Date) {
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

/** "heute 03:00", "gestern 22:15", "18.11., 07:42" (plus year when it is not this year). */
export function when(iso: string) {
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

/** "seit 07:42" today, "seit gestern 22:15", "seit 18.11., 07:42" otherwise. */
export function since(iso: string | undefined) {
  if (!iso) return "";
  const text = when(iso);
  return text ? `seit ${text.replace(/^heute /, "")}` : "";
}

/** When the device went down: its latest 'offline' transition from the monitor's event log;
 *  the log is capped at 50 entries, so fall back to "zuletzt erreichbar <lastSeen>". */
export function downSince(monitor: MonitorState, id: string, lastSeen: string): { text: string; title: string } {
  const event = monitor.events.find((e) => e.systemId === id && e.status === "offline");
  if (event) return { text: since(event.at), title: new Date(event.at).toLocaleString("de-DE") };
  if (lastSeen) return { text: `zuletzt erreichbar ${when(lastSeen)}`, title: new Date(lastSeen).toLocaleString("de-DE") };
  return { text: "", title: "" };
}
