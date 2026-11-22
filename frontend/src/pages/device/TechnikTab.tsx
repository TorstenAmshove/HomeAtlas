import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ExposureEntry, type ProbeResult, System, SystemAlias } from "../../lib/api";
import { Facts, NoticeLine, Section, StateChip, fullDate, type Notice } from "./common";

/** Tab "Technik": everything the scan and the read-only probe found (forensics "Gerät" 5). The
 *  container controls that used to sit inside "Container-Details" are in the "Steuern" tab. */
export default function TechnikTab({ system, monitorPorts, aliases, isAdmin, canProbe, probing, probeNotice, onProbe }: {
  system: System;
  monitorPorts: number[];
  /** Admin only (GET /systems/{id}/aliases); null while loading or for members. */
  aliases: SystemAlias[] | null;
  isAdmin: boolean;
  canProbe: boolean;
  probing: boolean;
  probeNotice: Notice;
  onProbe: () => void;
}) {
  const docker = system.extra?.docker;
  // "Erreichbar über ..." (GET /systems/{id}/exposure); empty when no reachability source is set up.
  const [exposure, setExposure] = useState<ExposureEntry[]>([]);
  useEffect(() => {
    let live = true;
    api.getSystemExposure(system.id).then((r) => { if (live) setExposure(r.entries); }).catch(() => {});
    return () => { live = false; };
  }, [system.id]);
  // Per-address ports of a merged multi-homed device -- see db.merge_systems / _record_interface.
  const interfaceEntries = Object.entries(
    (system.extra?.interfaces ?? {}) as Record<string, { openPorts?: number[] }>,
  );
  const multiHomed = interfaceEntries.length > 1;
  const probeResults = Object.entries((system.extra?.probe ?? {}) as Record<string, ProbeResult>);
  // Populated by pipeline.py after a scan with a Home Assistant credential.
  const printerSupplies = (system.extra?.printerSupplies ?? []) as { name: string; percent: number }[];
  // Populated by pipeline.py after a scan with an AdGuard Home credential attached to this system.
  const adguard = system.extra?.adguard as {
    protectionEnabled?: boolean; queries?: number; blocked?: number; blockedPercent?: number;
  } | undefined;
  const extraIps = Array.from(new Set((aliases ?? []).map((a) => a.ip).filter((ip) => ip && ip !== system.ip)));
  const extraMacs = Array.from(new Set((aliases ?? []).map((a) => a.mac).filter((m) => m && m !== system.mac)));

  return (
    <div className="dv-tab-body">
      <Section title="Technische Daten" id="dv-tech">
        <Facts rows={[
          ["Adresse im Netzwerk", system.ip && <span className="mono">{system.ip}</span>],
          ["Weitere Adressen", extraIps.length > 0 && <span className="mono">{extraIps.join(", ")}</span>],
          ["Hostname", system.hostname && <span className="mono">{system.hostname}</span>],
          ["Geräte-Kennung (MAC)", system.mac && <span className="mono">{system.mac}</span>],
          ["Weitere MACs", extraMacs.length > 0 && <span className="mono">{extraMacs.join(", ")}</span>],
          ["Hersteller", system.vendor],
          ["Modell", system.model],
          ["Standort", system.location],
          ["Zuletzt gesehen", fullDate(system.lastSeen)],
          ["Erstmals gesehen", fullDate(system.firstSeen)],
          ["Gefunden über", system.discoverySource],
          ["Überwachung", system.monitored === 1
            ? (monitorPorts.length > 0 ? `Port ${monitorPorts.join(", ")}` : "Ping")
            : ""],
        ]} />
      </Section>

      {multiHomed && (
        <Section title="Schnittstellen" id="dv-ifaces">
          <ul className="dv-rows">
            {interfaceEntries.map(([ip, iface]) => (
              <li key={ip} className="dv-row">
                <span className="dv-row-main"><span className="mono">{ip}</span></span>
                <span className="dv-row-sub mono">
                  {iface.openPorts?.length ? `Ports ${iface.openPorts.join(", ")}` : "keine offenen Ports"}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {(system.services?.length ?? 0) > 0 && (
        <Section title="Erreichbare Dienste" id="dv-services">
          <ul className="dv-rows">
            {system.services!.map((s) => (
              <li key={s.port} className="dv-row dv-row-stack">
                <span className="dv-row-main">
                  <span><span className="mono dv-port">{s.port}</span> {s.service}</span>
                  {multiHomed && (
                    <span className="dv-row-sub mono">
                      {interfaceEntries.filter(([, i]) => i.openPorts?.includes(s.port)).map(([ip]) => ip).join(", ")}
                    </span>
                  )}
                </span>
                {s.explanation && <span className="dv-row-sub">{s.explanation}</span>}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {exposure.length > 0 && (
        <Section title="Erreichbar über …" id="dv-exposure">
          <ul>
            {exposure.map((e, i) => (
              <li key={i}>
                <span className="mono">{e.host}</span> — {e.scope === "intern" ? "intern per TLS" : e.scope === "extern" ? "aus dem Internet" : "Portweiterleitung"}
                {" "}über {e.via}{e.status ? ` (${e.status})` : ""}{e.mtls ? ", Client-Zertifikat nötig" : ""}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {docker && (
        <Section title="Container-Details" id="dv-docker"
                 aside={isAdmin ? <Link className="dv-link" to="?tab=steuern">Starten, stoppen, Logs → Steuern</Link> : undefined}>
          <Facts mono rows={[
            ["Image", docker.image],
            ["Zustand", docker.status || docker.state],
            ["Compose-Projekt", docker.composeProject],
            ["Port-Zuordnungen (Docker)", docker.portMappings?.length > 0 ? docker.portMappings.join(", ") : ""],
            ["Datenablagen", docker.volumes?.length > 0 ? docker.volumes.join(", ") : ""],
          ]} />
        </Section>
      )}

      {system.kind === "printer" && printerSupplies.length > 0 && (
        <Section title="Verbrauchsmaterial" id="dv-supplies">
          <p className="dv-hint">Über Home Assistant ausgelesen — Stand vom letzten Netzwerk-Scan.</p>
          {printerSupplies.map((supply) => (
            <div key={supply.name} className="dv-supply">
              <div className="dv-supply-head">
                <span>{supply.name}</span>
                <span className="mono">{Math.round(supply.percent)}%</span>
              </div>
              <div className={`dv-bar${supply.percent <= 15 ? " low" : ""}`}>
                <div style={{ width: `${Math.max(0, Math.min(100, supply.percent))}%` }} />
              </div>
            </div>
          ))}
        </Section>
      )}

      {adguard && (
        <Section title="AdGuard Home" id="dv-adguard">
          <p className="dv-hint">DNS-Filterung — Stand vom letzten Netzwerk-Scan.</p>
          <Facts rows={[
            ["Schutz", <StateChip key="p" tone={adguard.protectionEnabled ? "ok" : "bad"}>
              {adguard.protectionEnabled ? "aktiv" : "deaktiviert"}
            </StateChip>],
            ["DNS-Anfragen", adguard.queries !== undefined ? adguard.queries.toLocaleString("de-DE") : ""],
            ["Blockiert", adguard.blocked !== undefined
              ? `${adguard.blocked.toLocaleString("de-DE")}${adguard.blockedPercent !== undefined ? ` (${adguard.blockedPercent}%)` : ""}`
              : ""],
          ]} />
        </Section>
      )}

      {(probeResults.length > 0 || canProbe) && (
        <Section title="Direkt vom Gerät ausgelesen" id="dv-probe"
                 aside={canProbe ? (
                   <button type="button" className="secondary dv-btn-small" onClick={onProbe} disabled={probing}>
                     {probing ? "Frage ab …" : probeResults.length > 0 ? "Erneut auslesen" : "Gerät auslesen"}
                   </button>
                 ) : undefined}>
          <p className="dv-hint">Über einen hinterlegten Zugang angemeldet und nur gelesen — nichts wurde verändert.</p>
          <NoticeLine notice={probeNotice} />
          {probeResults.length === 0 && <p className="dv-empty">Noch nicht ausgelesen.</p>}
          {probeResults.map(([source, result]) => (
            <div key={source} className="dv-probe">
              <StateChip tone={result.ok ? "ok" : "bad"}>{source}</StateChip>
              {result.ok ? (
                <dl className="dv-facts">
                  {Object.entries(result.facts).map(([key, fact]) => (
                    <div key={key} className="dv-fact">
                      <dt>{fact.label}</dt>
                      <dd>
                        {fact.value.includes("\n") ? (
                          <details>
                            <summary className="dv-link">{fact.value.split("\n").length} Zeilen — anzeigen</summary>
                            <pre className="dv-log mono">{fact.value}</pre>
                          </details>
                        ) : (
                          <span className="mono">{fact.value}</span>
                        )}
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="dv-empty">{result.error}</p>
              )}
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}
