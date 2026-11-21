import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type DnsResult, type MonitorState, type SpeedtestResult, type System } from "../../lib/api";
import { useAuth } from "../../App";
import { Skeleton } from "../../components/Skeleton";
import { useUrlState } from "../../lib/useUrlState";
import { clock, downSince } from "../../lib/time";
import { STATUS_LABEL } from "./inventoryModel";
import "./geraete.css";

/**
 * Netzplan of the redesigned UI (area "Geräte", tab "Netzplan").
 *
 * - `?view=layer3` keeps the chosen picture across Back and reload.
 * - One status line, not a banner plus a list naming the same devices (forensics "Netzplan" 3).
 *   It speaks about the same set as the Start page: "überwachte Geräte" from `/api/monitor`, and
 *   it only raises the alarm while monitoring is on (a stale "offline" from a switched-off monitor
 *   is not an outage), exactly like StartCalm's hero (numbers audit B3).
 * - The server-rendered SVG stays as it is, a static picture without zoom or drag controls
 *   (ADR-0008/0009). On phones it is drawn at twice the screen width inside a frame that scrolls
 *   sideways (the page itself never does), and the watched devices come first as a list with chips.
 * - DNS test, speedtest and "Jetzt prüfen" stay as actions under "Diagnose".
 */

/** Same grouping as the classic page (and topology.py): everything the plan does not draw. */
const DEVICE_GROUPS: [string, string[]][] = [
  ["Server & Speicher", ["server", "nas"]],
  ["Container & VMs", ["container", "vm"]],
  ["Computer & Mobilgeräte", ["pc", "mobile"]],
  ["Smart Home", ["smarthome", "iot"]],
  ["Wärme, Klima & Energie", ["heating", "climate", "energy"]],
  ["Drucker, Medien & Kameras", ["printer", "media", "camera"]],
  ["Weitere Geräte", ["other"]],
];

function StatusLine({ monitor, isAdmin }: { monitor: MonitorState | null; isAdmin: boolean }) {
  if (!monitor) return <Skeleton width="min(380px, 90%)" height={18} style={{ margin: "2px 0 10px" }} />;
  const total = monitor.systems.length;
  const live = monitor.enabled ? ` · live alle ${monitor.intervalSeconds} s` : "";
  if (!monitor.enabled) {
    return (
      <p className="plan-status" role="status">
        <span className="plan-status-main">Überwachung ist aus</span>
        <span className="geraete-quiet">
          Zustände bleiben auf dem Stand der letzten Prüfung.
          {isAdmin && <> Einschalten unter <Link to="/einstellungen">Einstellungen → Überwachung</Link>.</>}
        </span>
      </p>
    );
  }
  if (total === 0) {
    return (
      <p className="plan-status" role="status">
        <span className="plan-status-main">Noch kein Gerät unter Beobachtung</span>
        <span className="geraete-quiet">Als „kritisch“ markierte Geräte werden laufend geprüft.</span>
      </p>
    );
  }
  const offline = monitor.systems.filter((s) => s.status === "offline");
  if (offline.length > 0) {
    const single = offline.length === 1 ? downSince(monitor, offline[0].id, offline[0].lastSeen) : null;
    return (
      <p className="plan-status bad" role="status">
        <span className="plan-status-main">
          {offline.length} von {total} überwachten Geräten nicht erreichbar
        </span>
        <span className="geraete-quiet" title={single?.title || undefined}>
          {[offline.map((s) => s.name).join(", "), single?.text].filter(Boolean).join(" · ")}{live}
        </span>
      </p>
    );
  }
  if (monitor.systems.some((s) => s.status !== "online")) {
    return (
      <p className="plan-status" role="status">
        <span className="plan-status-main">Wird geprüft …</span>
        <span className="geraete-quiet">Noch nicht alle {total} überwachten Geräte haben geantwortet{live}</span>
      </p>
    );
  }
  return (
    <p className="plan-status ok" role="status">
      <span className="plan-status-main">Alle {total} überwachten Geräte erreichbar</span>
      <span className="geraete-quiet">{live.replace(/^ · /, "")}</span>
    </p>
  );
}

export default function PlanCalm() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [view, setView] = useUrlState("view", "physisch");
  const layer3 = view === "layer3";
  const [svg, setSvg] = useState("");
  const [svgError, setSvgError] = useState("");
  const [systems, setSystems] = useState<System[] | null>(null);
  const [monitor, setMonitor] = useState<MonitorState | null>(null);
  const [dns, setDns] = useState<{ result: DnsResult; at: Date } | null>(null);
  const [speed, setSpeed] = useState<{ result: SpeedtestResult; at: Date } | null>(null);
  const [checking, setChecking] = useState("");
  const [error, setError] = useState("");
  const [help, setHelp] = useState(false);
  const timer = useRef<number | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  // Where the frame is narrower than the picture (phones), it opens on the middle of the plan, where
  // the router and the backbone are drawn, instead of on its empty left edge.
  useEffect(() => {
    const el = canvasRef.current;
    if (el && svg) el.scrollLeft = Math.max(0, (el.scrollWidth - el.clientWidth) / 2);
  }, [svg]);

  const loadMonitor = useCallback(async () => {
    try {
      setMonitor(await api.monitor());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    // Fetched as text, not <img src>: an <img> would need its own authenticated request, and inline
    // markup gets the click targets (data-system-id) the plan relies on.
    const path = layer3 ? "/api/topology-layer3.svg" : "/api/topology.svg";
    let cancelled = false;
    setSvg("");
    setSvgError("");
    fetch(path, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error("Plan nicht verfügbar"))))
      .then((text) => { if (!cancelled) setSvg(text); })
      .catch((e) => { if (!cancelled) setSvgError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, [layer3]);

  useEffect(() => {
    api.listSystems().then((r) => setSystems(r.systems)).catch((e) => setError(e.message));
    void loadMonitor();
  }, [loadMonitor]);

  // Poll only while the tab is visible (same rule as the classic page and Start).
  useEffect(() => {
    function schedule(event?: Event) {
      if (timer.current) window.clearInterval(timer.current);
      if (event && document.visibilityState === "visible") void loadMonitor();
      if (document.visibilityState !== "visible") return;
      const seconds = Math.max(5, monitor?.intervalSeconds ?? 10);
      timer.current = window.setInterval(() => void loadMonitor(), seconds * 1000);
    }
    schedule();
    document.addEventListener("visibilitychange", schedule);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [monitor?.intervalSeconds, loadMonitor]);

  async function run(kind: "dns" | "speedtest" | "monitor") {
    setChecking(kind);
    setError("");
    try {
      if (kind === "dns") setDns({ result: (await api.dnsCheck()).result, at: new Date() });
      else if (kind === "speedtest") setSpeed({ result: (await api.speedtest()).result, at: new Date() });
      else {
        await api.monitorRunNow();
        await loadMonitor();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking("");
    }
  }

  // A host box with containers/VMs (data-expand) opens the list of its children; every other named
  // box opens its device page (same as the classic page).
  function handlePlanClick(e: MouseEvent<HTMLDivElement>) {
    const expandTarget = (e.target as Element).closest('[data-expand="1"]');
    if (expandTarget) {
      const id = expandTarget.getAttribute("data-system-id");
      if (id) navigate(`/geraete?parentId=${id}`);
      return;
    }
    const id = (e.target as Element).closest("[data-system-id]")?.getAttribute("data-system-id");
    if (id) navigate(`/geraete/${id}`);
  }

  const groupedSystems = DEVICE_GROUPS.map(([label, kinds]) => ({
    label,
    members: (systems ?? []).filter((s) => kinds.includes(s.kind) && s.importance !== "critical"),
  })).filter((g) => g.members.length > 0);


  return (
    <div className="geraete-calm">
      {error && <div className="notice error" role="alert">{error}</div>}
      <StatusLine monitor={monitor} isAdmin={isAdmin} />

      <div className="plan-bar">
        <div role="group" aria-label="Ansicht" className="plan-bar">
          <button type="button" className={`sbtn geraete-filter${!layer3 ? " active" : ""}`} aria-pressed={!layer3}
                  onClick={() => setView("physisch", { push: true })}>
            Physisch
          </button>
          <button type="button" className={`sbtn geraete-filter${layer3 ? " active" : ""}`} aria-pressed={layer3}
                  onClick={() => setView("layer3", { push: true })}>
            Layer 3 (Subnetze)
          </button>
        </div>
        <button type="button" className="sbtn geraete-filter" aria-expanded={help} aria-controls="plan-help"
                onClick={() => setHelp((open) => !open)}>
          ⓘ Wie lese ich den Plan?
        </button>
      </div>
      {help && (
        <div className="plan-help" id="plan-help">
        {layer3 ? (
          <p>
            Alle Geräte mit bekannter Adresse, gruppiert nach IP-Subnetz (/24) — nützlich, sobald mehr
            als ein Netz/VLAN im Einsatz ist (z. B. Gäste- oder IoT-Netz). Netze mit weniger als 3
            Geräten werden zur Übersichtlichkeit ausgeblendet, ebenso Router, deren Adresse nicht auf .1
            oder .254 endet (die üblichen Gateway-Adressen). Ein Router hinter einem anderen (z. B. ein
            per Zugangsdaten ausgelesener zweiter Router an der FritzBox) erscheint verkettet an seiner
            tatsächlichen Stelle — Internet → erster Router → zweiter Router → seine eigenen Netze —
            statt als eigenständiger Kasten direkt am Internet; ist die VLAN-ID einer Schnittstelle
            bekannt, steht sie mit in der Netz-Beschriftung.
          </p>
        ) : (
          <p>
            Internet, Router, Verteilung, dann als Nächstes die als „kritisch“ markierten Geräte —
            soweit bekannt mit ihrer tatsächlichen Verbindung (per LLDP erkannt), sonst am Netz
            angehängt. Alles andere steht ausklappbar darunter. Kritische Server mit Container/VMs
            zeigen nur sich selbst — ein Klick auf den Kasten öffnet die zugehörigen virtuellen Systeme.
            Ein Klick auf ein Gerät öffnet seine Seite.
          </p>
        )}
        </div>
      )}

      <div className="plan-layout">
        <figure className="plan-figure" aria-label={layer3 ? "Plan nach Subnetzen" : "Physischer Plan"}>
          <div className="plan-canvas" ref={canvasRef}>
            {svg ? (
              <div className="plan-canvas-inner" onClick={handlePlanClick}
                   dangerouslySetInnerHTML={{ __html: svg }} />
            ) : svgError ? (
              <p className="geraete-empty" style={{ padding: 16 }}>{svgError}</p>
            ) : (
              <div style={{ padding: 16 }} role="status">
                <span className="visually-hidden">Plan wird geladen …</span>
                <Skeleton height={220} radius={8} />
              </div>
            )}
          </div>
          <p className="plan-scroll-hint geraete-quiet">Im Rahmen seitlich verschieben, um den ganzen Plan zu sehen.</p>
        </figure>

        <section className="plan-watch" aria-labelledby="plan-watch-title">
          <h2 className="geraete-sec" id="plan-watch-title">Überwachte Geräte</h2>
          {!monitor ? (
            <Skeleton width="60%" />
          ) : monitor.systems.length === 0 ? (
            <p className="geraete-quiet">
              Geräte mit der Bedeutung „kritisch“ werden beim nächsten Scan automatisch aufgenommen — oder
              einzeln auf der Geräteseite.
            </p>
          ) : (
            <ul className="plan-list">
              {monitor.systems.map((s) => {
                const cls = !monitor.enabled ? "" : s.status === "online" ? "ok" : s.status === "offline" ? "bad" : "";
                const down = monitor.enabled && s.status === "offline" ? downSince(monitor, s.id, s.lastSeen) : null;
                return (
                  <li key={s.id}>
                    <Link to={`/geraete/${s.id}`} className="plan-row">
                      <span className="plan-row-main">
                        <span className="plan-row-name">{s.name}</span>
                        <span className="plan-row-sub">
                          {[s.ip || "keine Adresse", s.ports.length > 0 ? `Port ${s.ports.join(", ")}` : "Ping"].join(" · ")}
                        </span>
                      </span>
                      <span className={`geraete-chip ${cls}`} title={down?.title || undefined}>
                        <span className="dot" aria-hidden="true" />
                        {!monitor.enabled
                          ? `zuletzt ${STATUS_LABEL[s.status] ?? s.status}`
                          : s.status === "offline"
                            ? (down?.text.startsWith("seit") ? `${down.text} aus` : "nicht erreichbar")
                            : s.status === "online" ? "erreichbar" : "wird geprüft …"}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>

      {groupedSystems.length > 0 && (
        <section aria-labelledby="plan-rest-title">
          <h2 className="geraete-sec" id="plan-rest-title">Nicht im Plan gezeichnet</h2>
          {groupedSystems.map(({ label, members }) => {
            const online = members.filter((m) => m.status === "online").length;
            return (
              <details key={label} className="plan-more">
                <summary>
                  <span><b>{members.length}</b> {label}</span>
                  <span className="geraete-quiet">· {online > 0 ? `${online} erreichbar` : "keins erreichbar"}</span>
                </summary>
                <ul className="plan-list">
                  {members.map((m) => (
                    <li key={m.id}>
                      <Link to={`/geraete/${m.id}`} className="plan-row">
                        <span className="plan-row-main">
                          <span className="plan-row-name">{m.name}</span>
                          <span className="plan-row-sub">{m.ip || "keine Adresse"}</span>
                        </span>
                        <span className={`geraete-chip ${m.status === "online" ? "ok" : m.status === "offline" ? "bad" : ""}`}>
                          <span className="dot" aria-hidden="true" />{STATUS_LABEL[m.status] ?? m.status}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </details>
            );
          })}
        </section>
      )}

      {monitor && monitor.events.length > 0 && (
        <details className="plan-more">
          <summary><span>Letzte Zustandswechsel</span></summary>
          <p className="geraete-quiet" style={{ margin: "6px 0" }}>
            Nur Wechsel werden festgehalten — ein Gerät, das durchgehend läuft, erzeugt keine Einträge.
          </p>
          <ul className="plan-list">
            {monitor.events.slice(0, 12).map((e) => (
              <li key={e.id} className="plan-row">
                <span className="plan-row-main">
                  <span className="plan-row-name">{e.systemName ?? "unbekanntes Gerät"}</span>
                  <span className="plan-row-sub">{new Date(e.at).toLocaleString("de-DE")}{e.detail ? ` · ${e.detail}` : ""}</span>
                </span>
                <span className={`geraete-chip ${e.status === "online" ? "ok" : "bad"}`}>
                  <span className="dot" aria-hidden="true" />{e.status === "online" ? "wieder da" : "ausgefallen"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <section className="plan-diag" aria-labelledby="plan-diag-title">
        <h2 className="geraete-sec" id="plan-diag-title">Diagnose</h2>
        <div className="geraete-actions">
          {isAdmin && (
            <button type="button" className="secondary geraete-btn" onClick={() => void run("monitor")} disabled={checking !== ""}
                    title="Alle überwachten Geräte sofort prüfen, statt auf den nächsten Durchlauf zu warten">
              {checking === "monitor" ? "Prüfe …" : "Jetzt prüfen"}
            </button>
          )}
          <button type="button" className="secondary geraete-btn" onClick={() => void run("dns")} disabled={checking !== ""}
                  title="Prüft, ob Internetadressen in IP-Adressen übersetzt werden">
            {checking === "dns" ? "Prüfe …" : "DNS testen"}
          </button>
          <button type="button" className="secondary geraete-btn" onClick={() => void run("speedtest")} disabled={checking !== ""}
                  title="Lädt kurz einige Megabyte über Cloudflares öffentlichen Speedtest-Dienst">
            {checking === "speedtest" ? "Messe …" : "Speedtest"}
          </button>
        </div>
        {speed && (
          <div className={`plan-result ${speed.result.ok ? "ok" : "bad"}`} role="status">
            <span>{speed.result.ok ? speed.result.explanation : speed.result.error}</span>
            {speed.result.ok && (
              <div className="plan-speed">
                <span>Download <b>{speed.result.downloadMbps} Mbit/s</b></span>
                <span>Upload <b>{speed.result.uploadMbps} Mbit/s</b></span>
                <span>Latenz <b>{speed.result.pingMs} ms</b></span>
              </div>
            )}
            <span className="plan-result-time">Speedtest {clock(speed.at)}</span>
          </div>
        )}
        {dns && (
          <div className={`plan-result ${dns.result.resolvedCount === dns.result.totalCount ? "ok" : "bad"}`} role="status">
            <span>{dns.result.explanation}</span>
            <span className="plan-result-time">{dns.result.serversExplanation}</span>
            <ul className="plan-dns">
              {dns.result.results.map((r) => (
                <li key={r.name}>
                  <span className="mono">{r.name}</span>
                  {r.resolved
                    ? <span className="mono muted">{r.addresses.join(", ")}</span>
                    : <span className="geraete-chip bad"><span className="dot" aria-hidden="true" />nicht auflösbar</span>}
                  <span className={r.elapsedMs > 1500 ? "geraete-chip warn" : "muted"}>{r.elapsedMs} ms</span>
                </li>
              ))}
            </ul>
            <span className="plan-result-time">DNS-Test {clock(dns.at)}</span>
          </div>
        )}
      </section>
    </div>
  );
}
