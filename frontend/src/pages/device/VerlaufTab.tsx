import { useState } from "react";
import { api, type DeviceErrorEvent, type MonitorEvent } from "../../lib/api";
import { Skeleton } from "../../components/Skeleton";
import { NoticeLine, Section, StateChip, fullDate, when, type Notice } from "./common";

export const MONITOR_WORD: Record<string, string> = { online: "wieder erreichbar", offline: "nicht erreichbar" };
export const LEVEL_WORD: Record<string, string> = { error: "Fehler", warning: "Warnung", info: "Hinweis" };

/** Tab "Verlauf": monitor transitions, and the error log. Only reads. */
export default function VerlaufTab({ systemId, errorEvents, monitorEvents, monitorEnabled, isAdmin, onAcknowledged }: {
  systemId: string;
  errorEvents: DeviceErrorEvent[] | null;
  /** This device's entries of /api/monitor's event log (the newest 50 across all devices). */
  monitorEvents: MonitorEvent[];
  monitorEnabled: boolean;
  isAdmin: boolean;
  /** Called after an acknowledge so the page reloads the error list. */
  onAcknowledged: () => void;
}) {
  const [notice, setNotice] = useState<Notice>(null);

  async function acknowledge(eventId: string | null) {
    try {
      if (eventId) await api.acknowledgeSystemError(systemId, eventId);
      else await api.acknowledgeAllSystemErrors(systemId);
      onAcknowledged();
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div className="dv-tab-body">
      <NoticeLine notice={notice} />
      <Section title="Erreichbarkeit" id="dv-monitor">
        {monitorEvents.length === 0 ? (
          <p className="dv-empty">
            {monitorEnabled
              ? "Keine Zustandswechsel unter den letzten 50 der Dauerüberwachung (für alle Geräte zusammen)."
              : "Die Dauerüberwachung ist ausgeschaltet."}
          </p>
        ) : (
          <ul className="dv-rows">
            {monitorEvents.map((e) => (
              <li key={e.id} className="dv-row">
                <span className="dv-row-main">
                  <StateChip tone={e.status === "online" ? "ok" : e.status === "offline" ? "bad" : ""}>
                    {MONITOR_WORD[e.status] ?? e.status}
                  </StateChip>
                  {e.detail && <span className="dv-row-sub"> · {e.detail}</span>}
                </span>
                <time className="dv-row-time" dateTime={e.at} title={fullDate(e.at)}>{when(e.at)}</time>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Fehlerprotokoll" id="dv-errors">
        <p className="dv-hint">
          Was beim automatischen Auslesen oder bei der Dauerüberwachung an diesem Gerät fehlgeschlagen
          ist — SSH-Zeitüberschreitungen, abgelehnte Zugangsdaten, Ausfälle.
        </p>
        {errorEvents === null ? (
          <Skeleton width="60%" />
        ) : errorEvents.length === 0 ? (
          <p className="dv-empty">Nichts protokolliert.</p>
        ) : (
          <>
          {isAdmin && errorEvents.some((ev) => !ev.acknowledgedAt) && (
            <p>
              <button type="button" className="secondary dv-btn-small" onClick={() => void acknowledge(null)}>
                Alle quittieren
              </button>
            </p>
          )}
          <ul className="dv-rows">
            {errorEvents.map((ev) => (
              <li key={ev.id} className="dv-row dv-row-stack" style={ev.acknowledgedAt ? { opacity: 0.6 } : undefined}>
                <span className="dv-row-main">
                  <StateChip tone={ev.level === "error" ? "bad" : ev.level === "warning" ? "warn" : ""}>
                    {LEVEL_WORD[ev.level] ?? ev.level}
                  </StateChip>
                  <time className="dv-row-time" dateTime={ev.createdAt} title={fullDate(ev.createdAt)}>{when(ev.createdAt)}</time>
                </span>
                <span className="dv-row-text">{ev.message}</span>
                {ev.acknowledgedAt ? (
                  <span className="dv-row-sub">quittiert am {fullDate(ev.acknowledgedAt)}</span>
                ) : isAdmin ? (
                  <span className="dv-row-actions">
                    <button type="button" className="secondary dv-btn-small" onClick={() => void acknowledge(ev.id)}>
                      Quittieren
                    </button>
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          </>
        )}
      </Section>
    </div>
  );
}
