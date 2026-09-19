import { useEffect, useState } from "react";
import { useAuth } from "../App";
import { api, type NetworkResource } from "../lib/api";

const LABELS: Record<NetworkResource["kind"], string> = {
  network: "Netze & VLANs", wifi: "WLANs", wan: "Internet-Anschlüsse",
};

function details(resource: NetworkResource): string {
  const facts = resource.facts;
  if (resource.kind === "network") return [facts.cidr, facts.vlanId !== undefined ? `VLAN ${facts.vlanId}` : ""]
    .filter(Boolean).join(" · ");
  if (resource.kind === "wifi") return [facts.security, facts.networkName].filter(Boolean).join(" · ");
  return [facts.type, facts.ip].filter(Boolean).join(" · ");
}

export default function NetworksPage() {
  const { isAdmin } = useAuth();
  const [resources, setResources] = useState<NetworkResource[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [manualMd, setManualMd] = useState("");

  useEffect(() => {
    api.listNetworkResources().then((result) => setResources(result.resources))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function save(resource: NetworkResource) {
    try {
      const result = await api.updateNetworkResource(resource.id, manualMd);
      setResources((current) => current.map((item) => item.id === resource.id ? result.resource : item));
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <div className="page-header"><div><h1>Netze & WLAN</h1><p>Vom Controller erfasste VLANs, WLANs und Internet-Anschlüsse.</p></div></div>
      {error && <div className="notice error">{error}</div>}
      {(["network", "wifi", "wan"] as const).map((kind) => {
        const items = resources.filter((resource) => resource.kind === kind);
        if (!items.length) return null;
        return <div className="card" key={kind}>
          <h2>{LABELS[kind]}</h2>
          <table><thead><tr><th>Name</th><th>Standort</th><th>Details</th><th>Notiz</th></tr></thead><tbody>
            {items.map((resource) => <tr key={resource.id}>
              <td>{resource.name}{!resource.enabled && " (deaktiviert)"}</td><td>{resource.siteName}</td><td>{details(resource) || "-"}</td>
              <td>{editing === resource.id ? <div className="row"><input value={manualMd} onChange={(e) => setManualMd(e.target.value)} /><button className="small" onClick={() => void save(resource)}>Speichern</button></div>
                : <>{resource.manualMd || "-"}{isAdmin && <button className="secondary small" style={{ marginLeft: 8 }} onClick={() => { setEditing(resource.id); setManualMd(resource.manualMd); }}>Bearbeiten</button>}</>}</td>
            </tr>)}
          </tbody></table>
        </div>;
      })}
      {!resources.length && !error && <div className="card"><p className="muted">Noch keine Controller-Daten. Lege unter Zugänge einen UniFi-API-Key an und starte einen Scan.</p></div>}
    </>
  );
}
