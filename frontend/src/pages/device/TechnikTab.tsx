import { useEffect, useState } from "react";
import { api, type ExposureEntry, type ProbeResult, System, SystemAlias } from "../../lib/api";
import { Facts, NoticeLine, Section, StateChip, fullDate, type Notice } from "./common";

type PortNet = { vlan: number | null; name: string; known?: boolean };
type SwitchPort = {
  port: number; name: string; profile: string; native: PortNet;
  tagged: { mode: string; excluded?: PortNet[] };
  uplink?: boolean;
};

/** `VLAN 10 Default`; an ID the scan could not resolve reads "unbekanntes Netz" (ADR-0026). */
function netLabel(net: PortNet | undefined): string {
  if (!net) return "–";
  if (net.known === false) return "unbekanntes Netz";
  const text = [net.vlan != null ? `VLAN ${net.vlan}` : "", net.name].filter(Boolean).join(" ");
  return text || "–";
}

function taggedLabel(tagged: SwitchPort["tagged"] | undefined): string {
  if (tagged?.mode === "all") {
    const excluded = (tagged.excluded ?? []).map((n) => netLabel({ ...n, known: n.vlan != null || !!n.name }));
    return excluded.length ? `alle außer ${excluded.join(", ")}` : "alle";
  }
  if (tagged?.mode === "none") return "keine";
  if (tagged?.mode === "custom") return "benutzerdefiniert (Liste nicht gelesen)";
  return "–";
}

/** Tab "Technik": everything the scan and the read-only probe found (forensics "Gerät" 5). The
 *  HomeAtlas has no container controls; use Portainer or the Docker host itself. */
export default function TechnikTab({ system, monitorPorts, aliases, canProbe, probing, probeNotice, onProbe }: {
  system: System;
  monitorPorts: number[];
  /** Admin only (GET /systems/{id}/aliases); null while loading or for members. */
  aliases: SystemAlias[] | null;
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
  // Switch ports with their VLANs (extra.unifi.ports, ADR-0026); the attached device per port comes
  // from the other devices' extra.unifi.connection, read from the device list like DevicePage does.
  const storedPorts = (system.extra as any)?.unifi?.ports?.ports;
  const ports: SwitchPort[] = Array.isArray(storedPorts)
    ? storedPorts.filter((p: any) => p && Number.isInteger(p.port))
    : [];
  const [attached, setAttached] = useState<Record<number, string[]>>({});
  const [uplinkName, setUplinkName] = useState("");
  useEffect(() => {
    setAttached({});
    setUplinkName("");
    if (ports.length === 0) return;
    let live = true;
    api.listSystems().then((r) => {
      const byPort: Record<number, string[]> = {};
      for (const other of r.systems) {
        const conn = (other.extra as any)?.unifi?.connection;
        if (other.id !== system.id && conn?.type === "wired" && conn.systemId === system.id && Number.isInteger(conn.port)) {
          (byPort[conn.port] ??= []).push(other.name);
        }
      }
      // The switch's own uplink port reads "Uplink -> <neighbour>" (ADR-0027); the neighbour is the
      // device of this device's own extra.unifi.connection.
      const ownConn = (system.extra as any)?.unifi?.connection;
      const neighbour = ownConn?.systemId ? r.systems.find((o) => o.id === ownConn.systemId) : undefined;
      if (live) {
        setAttached(byPort);
        setUplinkName(neighbour?.name ?? "");
      }
    }).catch(() => {});
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [system.id, ports.length]);
  const probeResults = Object.entries((system.extra?.probe ?? {}) as Record<string, ProbeResult>);
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

      {ports.length > 0 && (
        <Section title="Ports und VLANs" id="dv-ports">
          <table>
            <thead>
              <tr><th>Port</th><th>Name</th><th>Nativ</th><th>Tagged</th><th>Angeschlossenes Gerät</th></tr>
            </thead>
            <tbody>
              {ports.map((p) => (
                <tr key={p.port}>
                  <td>{p.port}</td>
                  <td>{p.name || "–"}</td>
                  <td>{netLabel(p.native)}</td>
                  <td>{taggedLabel(p.tagged)}</td>
                  <td>{[...(p.uplink ? [uplinkName ? `Uplink → ${uplinkName}` : "Uplink"] : []),
                    ...(attached[p.port] ?? [])].join(", ") || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

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
        <Section title="Container-Details" id="dv-docker">
          <Facts mono rows={[
            ["Image", docker.image],
            ["Zustand", docker.status || docker.state],
            ["Compose-Projekt", docker.composeProject],
            ["Port-Zuordnungen (Docker)", docker.portMappings?.length > 0 ? docker.portMappings.join(", ") : ""],
            ["Datenablagen", docker.volumes?.length > 0 ? docker.volumes.join(", ") : ""],
          ]} />
          {docker.dockerSocket && (
            <NoticeLine notice={{ kind: "error", text: "Container hat Vollzugriff auf Docker (entspricht Root auf dem Host). Empfehlung: Zugriff über einen Socket-Proxy mit nur lesenden Pfaden statt docker.sock einzubinden." }} />
          )}
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
                <p className="dv-empty">
                  {result.superseded && "nachrangig – ein anderer Zugang dieser Art funktioniert. "}
                  {result.error}
                </p>
              )}
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}
