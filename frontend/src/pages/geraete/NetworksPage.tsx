import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../../App";
import { api, type NetworkResource } from "../../lib/api";
import { Skeleton } from "../../components/Skeleton";
import Markdown from "../../components/Markdown";
import "./geraete.css";

/**
 * "Netze & WLAN" in the UI (area "Geräte"): a plain list per kind, no page title (the tab says it), and an empty state
 * that says what is missing -- these entries only come from a controller account (today UniFi,
 * see pipeline.py → db.sync_network_resources), so an empty page is usually a missing Zugang.
 */

const LABELS: Record<NetworkResource["kind"], string> = {
  network: "Netze & VLANs", wifi: "WLANs", wan: "Internet-Anschlüsse",
};

function details(resource: NetworkResource): string {
  const facts = resource.facts;
  if (resource.kind === "network") {
    return [facts.cidr, facts.vlanId !== undefined ? `VLAN ${facts.vlanId}` : ""].filter(Boolean).join(" · ");
  }
  if (resource.kind === "wifi") return [facts.security, facts.networkName].filter(Boolean).join(" · ");
  return [facts.type, facts.ip].filter(Boolean).join(" · ");
}

export default function NetworksPage() {
  const { isAdmin } = useAuth();
  const [resources, setResources] = useState<NetworkResource[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [manualMd, setManualMd] = useState("");
  const [saving, setSaving] = useState(false);
  const [showInactive, setShowInactive] = useState(false);

  // Always load everything; the switch only filters, so a page with only inactive entries is not "empty".
  useEffect(() => {
    api.listNetworkResources(undefined, false).then((result) => setResources(result.resources))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function save(resource: NetworkResource) {
    setSaving(true);
    try {
      const result = await api.updateNetworkResource(resource.id, manualMd);
      setResources((current) => (current ?? []).map((item) => (item.id === resource.id ? result.resource : item)));
      setEditing(null);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (error && resources === null) return <div className="geraete-page"><div className="notice error">{error}</div></div>;
  if (resources === null) {
    return (
      <div className="geraete-page" role="status">
        <span className="visually-hidden">Wird geladen …</span>
        <Skeleton width={120} height={12} style={{ margin: "18px 0 10px" }} />
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="net-row" style={{ borderBottom: "1px solid var(--c-line)" }}>
            <div style={{ flex: 1, display: "grid", gap: 6 }}>
              <Skeleton width={`${40 + ((i * 17) % 35)}%`} />
              <Skeleton width="30%" height={10} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  const visible = resources.filter((resource) => showInactive || resource.active);

  if (resources.length === 0) {
    return (
      <div className="geraete-page">
        {error && <div className="notice error" role="alert">{error}</div>}
        <div className="geraete-empty">
          <h2>Noch keine Netze erfasst</h2>
          <p>
            Netze und VLANs, WLANs und Internet-Anschlüsse liest HomeAtlas aus dem Netzwerk-Controller
            (UniFi). Dafür braucht es einen Zugang vom Typ „UniFi Network (API-Key)“; der nächste Scan
            trägt dann alles hier ein.
          </p>
          {isAdmin ? (
            <div className="geraete-actions">
              <Link className="geraete-btn primary" to="/zugaenge">Zugang anlegen</Link>
              <Link className="geraete-btn" to="/scan">Netzwerk scannen</Link>
            </div>
          ) : (
            <p>Den Zugang kann ein Administrator unter „Zugänge“ hinterlegen.</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="geraete-page">
      {error && <div className="notice error" role="alert">{error}</div>}
      <label className="net-toggle">
        <input type="checkbox" checked={showInactive}
               onChange={(e) => { setShowInactive(e.target.checked); setEditing(null); }} />
        Inaktive anzeigen
      </label>
      {(["network", "wifi", "wan"] as const).map((kind) => {
        const items = visible.filter((resource) => resource.kind === kind);
        if (!items.length) return null;
        return (
          <section key={kind} aria-labelledby={`net-${kind}`}>
            <h2 className="geraete-sec" id={`net-${kind}`}>{LABELS[kind]}</h2>
            <ul className="plan-list">
              {items.map((resource) => {
                const sub = [resource.siteName, details(resource)].filter(Boolean).join(" · ");
                return (
                  <li key={resource.id} className="net-row">
                    <div className="net-row-main">
                      <div className="net-row-name">
                        {resource.name}
                        {!resource.active && <span className="geraete-chip" style={{ marginLeft: 8 }}>nicht mehr im Controller</span>}
                        {!!resource.active && !resource.enabled && <span className="geraete-chip" style={{ marginLeft: 8 }}>deaktiviert</span>}
                      </div>
                      {sub && <div className="net-row-sub">{sub}</div>}
                      {editing !== resource.id && resource.manualMd && <div className="net-note"><Markdown>{resource.manualMd}</Markdown></div>}
                    </div>
                    {isAdmin && editing !== resource.id && (
                      <button type="button" className="secondary geraete-btn"
                              onClick={() => { setEditing(resource.id); setManualMd(resource.manualMd); }}
                              aria-label={`Notiz zu ${resource.name} ${resource.manualMd ? "bearbeiten" : "hinzufügen"}`}>
                        {resource.manualMd ? "Notiz bearbeiten" : "Notiz hinzufügen"}
                      </button>
                    )}
                    {editing === resource.id && (
                      <form className="net-edit" onSubmit={(e) => { e.preventDefault(); void save(resource); }}>
                        <textarea value={manualMd} onChange={(e) => setManualMd(e.target.value)} autoFocus
                                  rows={4} maxLength={2000} aria-label={`Notiz zu ${resource.name}`}
                                  placeholder="z. B. nur für Besuch (Markdown möglich)" />
                        <div className="net-count">{manualMd.length} / 2000</div>
                        <button type="submit" className="geraete-btn" disabled={saving}>{saving ? "Speichere …" : "Speichern"}</button>
                        <button type="button" className="secondary geraete-btn" disabled={saving} onClick={() => setEditing(null)}>
                          Abbrechen
                        </button>
                      </form>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
