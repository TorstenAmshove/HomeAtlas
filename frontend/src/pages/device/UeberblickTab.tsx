import { Link } from "react-router-dom";
import type { Account, DeviceErrorEvent, MonitorEvent, System } from "../../lib/api";
import Markdown from "../../components/Markdown";
import { SkeletonText } from "../../components/Skeleton";
import { Facts, Section, StateChip, fullDate, when } from "./common";
import { LEVEL_WORD, MONITOR_WORD } from "./VerlaufTab";

interface HistoryItem { key: string; at: string; tone: "ok" | "bad" | "warn" | ""; title: string; text: string }

/** Newest first, monitor transitions and error-log entries in one list (same data as "Verlauf"). */
export function recentHistory(monitorEvents: MonitorEvent[], errorEvents: DeviceErrorEvent[] | null): HistoryItem[] {
  const items: HistoryItem[] = [
    ...monitorEvents.map((e) => ({
      key: `m-${e.id}`, at: e.at, tone: (e.status === "online" ? "ok" : e.status === "offline" ? "bad" : "") as HistoryItem["tone"],
      title: MONITOR_WORD[e.status] ?? e.status, text: e.detail,
    })),
    ...(errorEvents ?? []).map((e) => ({
      key: `e-${e.id}`, at: e.createdAt, tone: (e.level === "error" ? "bad" : e.level === "warning" ? "warn" : "") as HistoryItem["tone"],
      title: LEVEL_WORD[e.level] ?? e.level, text: e.message,
    })),
  ];
  return items.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
}

/** Tab "Überblick": what the device is for, a short Steckbrief and the latest history. */
export default function UeberblickTab({ system, derived, accounts, isAdmin, history }: {
  system: System;
  derived: string;
  accounts: Account[];
  isAdmin: boolean;
  history: HistoryItem[] | null;
}) {
  const needsPoe = (system.tags ?? []).some((t) => t.toLowerCase().includes("poe"));
  const latest = history?.slice(0, 3) ?? [];
  // The derived text often is just the purpose sentence again; print it once.
  const showDerived = Boolean(derived) && derived.trim() !== (system.purpose ?? "").trim();

  return (
    <div className="dv-overview">
      <div>
        <Section title="Wofür" id="dv-purpose">
          {system.purpose && <p className="dv-purpose">{system.purpose}</p>}
          {system.descriptionMd ? (
            <Markdown>{system.descriptionMd}</Markdown>
          ) : showDerived ? (
            <>
              <Markdown>{derived}</Markdown>
              <p className="dv-hint">
                Aus Gerätetyp und gefundenen Diensten abgeleitet.
                {isAdmin && " Über „Bearbeiten“ lässt sich eine eigene Beschreibung hinterlegen, die dann Vorrang hat."}
              </p>
            </>
          ) : !system.purpose && !derived ? (
            <p className="dv-empty">Noch keine Beschreibung. Ein Netzwerk-Scan mit KI-Unterstützung ergänzt sie automatisch.</p>
          ) : null}
          {system.notes && <p className="dv-hint"><strong>Notiz:</strong> {system.notes}</p>}
        </Section>

        <Section title="Zuletzt" id="dv-recent"
                 aside={<Link className="dv-link" to="?tab=verlauf">Alle anzeigen</Link>}>
          {history === null ? (
            <SkeletonText lines={2} />
          ) : latest.length === 0 ? (
            <p className="dv-empty">Keine Ausfälle oder Fehler protokolliert.</p>
          ) : (
            <ul className="dv-rows">
              {latest.map((item) => (
                <li key={item.key} className="dv-row dv-row-stack">
                  <span className="dv-row-main">
                    <StateChip tone={item.tone}>{item.title}</StateChip>
                    <time className="dv-row-time" dateTime={item.at} title={fullDate(item.at)}>{when(item.at)}</time>
                  </span>
                  {item.text && <span className="dv-row-text">{item.text}</span>}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <div>
        <Section title="Steckbrief" id="dv-card">
          <Facts rows={[
            ["Modell", system.model],
            ["Hersteller", system.vendor],
            ["Standort", system.location],
            ["Strom", needsPoe ? "braucht PoE (PoE-Switch oder Injector)" : ""],
            ["Schlagworte", (system.tags ?? []).join(", ")],
            ["Zugänge", isAdmin && accounts.length > 0
              ? <Link className="dv-link" to="?tab=zugaenge">{accounts.length === 1 ? "1 Zugang hinterlegt" : `${accounts.length} Zugänge hinterlegt`}</Link>
              : ""],
          ]} />
          {!system.model && !system.vendor && !system.location && !needsPoe && (
            <p className="dv-empty">Modell und Standort sind noch nicht eingetragen.</p>
          )}
        </Section>
      </div>
    </div>
  );
}
