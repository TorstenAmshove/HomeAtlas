import { useState } from "react";
import { api, type ConfigVersion, type DeviceErrorEvent, type MonitorEvent } from "../../lib/api";
import { downloadConfigVersion } from "../../lib/device";
import { Skeleton } from "../../components/Skeleton";
import { LogBox, NoticeLine, Section, StateChip, fullDate, when, type Notice } from "./common";

export const MONITOR_WORD: Record<string, string> = { online: "wieder erreichbar", offline: "nicht erreichbar" };
export const LEVEL_WORD: Record<string, string> = { error: "Fehler", warning: "Warnung", info: "Hinweis" };

/** Tab "Verlauf": monitor transitions, the error log and (routers/switches, admin) the config
 *  history. Only reads; a stored config is never written back to the device. */
export default function VerlaufTab({ systemId, errorEvents, monitorEvents, monitorEnabled, configVersions, showConfig, isAdmin, onAcknowledged }: {
  systemId: string;
  errorEvents: DeviceErrorEvent[] | null;
  /** This device's entries of /api/monitor's event log (the newest 50 across all devices). */
  monitorEvents: MonitorEvent[];
  monitorEnabled: boolean;
  configVersions: ConfigVersion[] | null;
  showConfig: boolean;
  isAdmin: boolean;
  /** Called after an acknowledge so the page reloads the error list. */
  onAcknowledged: () => void;
}) {
  const [preview, setPreview] = useState<ConfigVersion | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  async function toggleVersion(version: ConfigVersion) {
    if (preview?.id === version.id) {
      setPreview(null);
      return;
    }
    try {
      setPreview((await api.getConfigVersion(systemId, version.id)).version);
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    }
  }

  async function acknowledge(eventId: string | null) {
    try {
      if (eventId) await api.acknowledgeSystemError(systemId, eventId);
      else await api.acknowledgeAllSystemErrors(systemId);
      onAcknowledged();
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    }
  }

  async function download(version: ConfigVersion) {
    try {
      await downloadConfigVersion(systemId, version);
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

      {showConfig && (
        <Section title="Konfigurationsverlauf" id="dv-config">
          <p className="dv-hint">
            Textkonfigurationen, die beim Auslesen des Geräts gesichert wurden — nur zum Nachsehen,
            wird nie automatisch auf das Gerät zurückgeschrieben. Kann Zugangsdaten wie
            Community-Strings enthalten, deshalb verschlüsselt gespeichert.
          </p>
          {configVersions === null ? (
            <Skeleton width="50%" />
          ) : configVersions.length === 0 ? (
            <p className="dv-empty">Noch keine Sicherung vorhanden.</p>
          ) : (
            <ul className="dv-rows">
              {configVersions.map((v) => (
                <li key={v.id} className="dv-row dv-row-stack">
                  <span className="dv-row-main">
                    <span>{v.label}</span>
                    <time className="dv-row-time" dateTime={v.createdAt} title={fullDate(v.createdAt)}>{when(v.createdAt)}</time>
                  </span>
                  <span className="dv-row-sub">{v.source} · {Math.round(v.size / 100) / 10} kB</span>
                  <span className="dv-row-actions">
                    <button type="button" className="secondary dv-btn-small" aria-expanded={preview?.id === v.id}
                            onClick={() => void toggleVersion(v)}>
                      {preview?.id === v.id ? "Einklappen" : "Ansehen"}
                    </button>
                    <button type="button" className="secondary dv-btn-small" onClick={() => void download(v)}>Herunterladen</button>
                  </span>
                  {preview?.id === v.id && <LogBox label={`Konfiguration ${v.label}`}>{preview.content}</LogBox>}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}
