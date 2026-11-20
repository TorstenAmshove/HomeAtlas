import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Dashboard, type DiagnosticResult, type MonitorState, type System } from "../../lib/api";
import { useAuth } from "../../App";
import { Skeleton } from "../../components/Skeleton";
import "./start.css";

/**
 * Start page of the redesigned UI (direction B, docs/redesign/5-information-architecture.md), shown
 * instead of DashboardPage while `uiCalm` is on. Summary first: a status hero answers "is anything
 * down?", one quiet line carries every count exactly once, then the lists.
 *
 * Numbers come from the same queries as before (docs/redesign/3-numbers-audit.md):
 * - the alarm set is `/api/monitor` → systems with status 'offline', the same set the Netzplan
 *   page reports (B3), not `counts.offline` (which includes sleeping phones);
 * - "+N weitere" is `counts.critical - criticalSystems.length`, pure presentation (B1);
 * - a critical device that the monitor does not poll (no IP/hostname, monitoring off, or not
 *   flagged) shows "Stand letzter Scan" instead of a live chip (B2).
 * `recentlyChanged` is still delivered but deliberately not shown (see the PR for this page).
 */

const STATUS_WORD: Record<string, string> = { online: "erreichbar", offline: "nicht erreichbar" };

function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function clock(d: Date) {
  return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

/** "heute 03:00", "gestern 22:15", "18.11., 07:42" (plus year when it is not this year). */
function when(iso: string) {
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
function since(iso: string | undefined) {
  if (!iso) return "";
  const text = when(iso);
  return text ? `seit ${text.replace(/^heute /, "")}` : "";
}

/** When the device went down: its latest 'offline' transition from the monitor's event log;
 *  the log is capped at 50 entries, so fall back to "zuletzt erreichbar <lastSeen>". */
function downSince(monitor: MonitorState, id: string, lastSeen: string): { text: string; title: string } {
  const event = monitor.events.find((e) => e.systemId === id && e.status === "offline");
  if (event) return { text: since(event.at), title: new Date(event.at).toLocaleString("de-DE") };
  if (lastSeen) return { text: `zuletzt erreichbar ${when(lastSeen)}`, title: new Date(lastSeen).toLocaleString("de-DE") };
  return { text: "", title: "" };
}

function StartSkeleton() {
  return (
    <div className="start-calm" role="status" aria-live="polite">
      <span className="visually-hidden">Wird geladen …</span>
      <div className="start-hero start-hero-neutral">
        <Skeleton width="min(340px, 80%)" height={22} />
        <Skeleton width="min(260px, 60%)" style={{ marginTop: 8 }} />
      </div>
      <Skeleton width="min(420px, 90%)" style={{ margin: "18px 0 6px" }} />
      <div className="start-grid">
        {[6, 5].map((rows, col) => (
          <section key={col}>
            <Skeleton width={120} height={12} style={{ margin: "18px 0 10px" }} />
            {Array.from({ length: rows }, (_, i) => (
              <div key={i} className="start-row start-row-skeleton">
                <div style={{ flex: 1, display: "grid", gap: 6 }}>
                  <Skeleton width={`${50 + ((i * 17) % 35)}%`} />
                  {col === 0 && <Skeleton width="30%" height={10} />}
                </div>
                <Skeleton width={col === 0 ? 72 : 20} height={12} />
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

type CriticalSystem = Dashboard["criticalSystems"][number];

function CriticalRow({ s, live, monitor }: { s: CriticalSystem; live: boolean; monitor: MonitorState }) {
  const address = s.ip || s.hostname;
  const probe = s.monitorPortsEffective && s.monitorPortsEffective.length > 0
    ? `Port ${s.monitorPortsEffective.join(", ")}`
    : "Ping";
  let chip;
  if (!live) {
    chip = (
      <span className="start-chip" title="Wird nicht laufend geprüft – Zustand vom letzten Scan">
        Stand letzter Scan
      </span>
    );
  } else if (s.status === "online") {
    chip = <span className="start-chip ok"><span className="dot" aria-hidden="true" />erreichbar</span>;
  } else if (s.status === "offline") {
    const down = downSince(monitor, s.id, s.lastSeen);
    chip = (
      <span className="start-chip bad" title={down.title || undefined}>
        <span className="dot" aria-hidden="true" />
        {/* Phone: the short form keeps the device name readable next to the chip. */}
        <span className="start-chip-long">{down.text.startsWith("seit") ? `${down.text} ` : ""}nicht erreichbar</span>
        <span className="start-chip-short">{down.text.startsWith("seit") ? `${down.text} ` : ""}aus</span>
      </span>
    );
  } else {
    chip = <span className="start-chip"><span className="dot" aria-hidden="true" />wird geprüft …</span>;
  }
  const sub = live
    ? `${address} · ${probe}`
    : `${address || "keine Adresse"} · beim Scan ${STATUS_WORD[s.status] ?? "unbekannt"}`;
  return (
    <li>
      <Link to={`/geraete/${s.id}`} className="start-row">
        <span className="start-row-main">
          <span className="start-row-name">{s.name}</span>
          <span className="start-row-sub">{sub}</span>
        </span>
        {chip}
      </Link>
    </li>
  );
}

function StatusHero({ data, monitor, isAdmin, hasEmergencyDoc }: {
  data: Dashboard;
  monitor: MonitorState;
  isAdmin: boolean;
  hasEmergencyDoc: boolean;
}) {
  const offline = monitor.systems.filter((s) => s.status === "offline");

  if (offline.length > 0) {
    const first = offline[0];
    const single = offline.length === 1;
    const down = single ? downSince(monitor, first.id, first.lastSeen) : { text: "", title: "" };
    const others = monitor.systems.filter((s) => s.status === "online").length;
    const details = single
      ? [down.text, "wichtiges Gerät", others > 0 ? `die anderen ${others} laufen` : ""]
      : [offline.map((s) => s.name).join(", ")];
    return (
      <section className="start-hero start-hero-bad" aria-labelledby="start-hero-title">
        <h2 id="start-hero-title">
          {single ? `${first.name} ist nicht erreichbar` : `${offline.length} wichtige Geräte nicht erreichbar`}
        </h2>
        <p className="start-hero-sub" title={down.title || undefined}>{details.filter(Boolean).join(" · ")}</p>
        <div className="start-actions">
          {/* Several down: the Netzplan lists exactly this set (same /api/monitor query). */}
          <Link className="start-btn primary" to={single ? `/geraete/${first.id}` : "/plan"}>Ansehen</Link>
          <Link className="start-btn" to="/assistent">Assistent fragen</Link>
          {hasEmergencyDoc && <Link className="start-btn" to="/dokumentation/notfall">Notfall-Checkliste</Link>}
        </div>
      </section>
    );
  }

  if (data.counts.total === 0) {
    return (
      <section className="start-hero start-hero-neutral" aria-labelledby="start-hero-title">
        <h2 id="start-hero-title">Noch nichts dokumentiert</h2>
        <p className="start-hero-sub">Ein Netzwerk-Scan findet die Geräte im Haus automatisch.</p>
        {isAdmin && (
          <div className="start-actions">
            <Link className="start-btn primary" to="/scan">Netzwerk scannen</Link>
          </div>
        )}
      </section>
    );
  }

  if (!monitor.enabled) {
    return (
      <section className="start-hero start-hero-neutral" aria-labelledby="start-hero-title">
        <h2 id="start-hero-title">Überwachung ist aus</h2>
        <p className="start-hero-sub">
          Zustände bleiben auf dem Stand des letzten Scans.
          {isAdmin && <> Einschalten unter <Link to="/einstellungen">Einstellungen → Überwachung</Link>.</>}
        </p>
      </section>
    );
  }

  if (monitor.systems.length === 0) {
    return (
      <section className="start-hero start-hero-neutral" aria-labelledby="start-hero-title">
        <h2 id="start-hero-title">Noch kein Gerät unter Beobachtung</h2>
        <p className="start-hero-sub">
          Geräte, ohne die im Haus etwas ausfällt, in der Geräteansicht als kritisch markieren – sie
          werden dann laufend geprüft.
        </p>
      </section>
    );
  }

  return (
    <section className="start-hero start-hero-ok" aria-labelledby="start-hero-title">
      <h2 id="start-hero-title">Alles erreichbar</h2>
      <p className="start-hero-sub">Alle wichtigen Geräte antworten.</p>
    </section>
  );
}

export default function StartCalm() {
  const { isAdmin } = useAuth();
  const [data, setData] = useState<Dashboard | null>(null);
  const [monitor, setMonitor] = useState<MonitorState | null>(null);
  const [error, setError] = useState("");
  const [hasEmergencyDoc, setHasEmergencyDoc] = useState(false);
  const [check, setCheck] = useState<{ result: DiagnosticResult | null; error: string; at: Date } | null>(null);
  const [checking, setChecking] = useState(false);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [dashboard, monitorState] = await Promise.all([api.dashboard(), api.monitor()]);
      setData(dashboard);
      setMonitor(monitorState);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Same cadence and visibility rule as the classic page: the monitor's interval, never under 5 s,
  // and nothing while the tab is hidden.
  useEffect(() => {
    function schedule() {
      if (timer.current) window.clearInterval(timer.current);
      if (document.visibilityState !== "visible" || !data?.monitorEnabled) return;
      const seconds = Math.max(5, data?.monitorIntervalSeconds ?? 10);
      timer.current = window.setInterval(() => void load(), seconds * 1000);
    }
    schedule();
    document.addEventListener("visibilitychange", schedule);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [data?.monitorIntervalSeconds, data?.monitorEnabled, load]);

  // The "Notfall-Checkliste" action only appears when that chapter exists. Asked once, and only
  // while something is down; a failure just leaves the action out.
  const anyDown = Boolean(monitor?.systems.some((s) => s.status === "offline"));
  useEffect(() => {
    if (!anyDown || hasEmergencyDoc) return;
    let cancelled = false;
    api.listDocs()
      .then((r) => { if (!cancelled) setHasEmergencyDoc(r.pages.some((p) => p.slug === "notfall")); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [anyDown, hasEmergencyDoc]);

  async function runInternetCheck() {
    setChecking(true);
    try {
      const { result } = await api.runDiagnostic("internet_check");
      setCheck({ result, error: "", at: new Date() });
    } catch (e) {
      setCheck({ result: null, error: e instanceof Error ? e.message : String(e), at: new Date() });
    } finally {
      setChecking(false);
    }
  }

  if (error) return <div className="notice error">{error}</div>;
  if (!data || !monitor) return <StartSkeleton />;

  const { counts } = data;
  const monitoredIds = new Set(monitor.systems.map((s) => s.id));
  const isLive = (s: System) => data.monitorEnabled && monitoredIds.has(s.id);
  const hiddenCritical = Math.max(0, counts.critical - data.criticalSystems.length);
  const kinds = Object.entries(data.byKind).sort((a, b) => b[1] - a[1]);
  const checkOk = check?.result
    ? Boolean(check.result.internetReachable && check.result.dnsWorks && check.result.websitesLoad)
    : false;

  return (
    <div className="start-calm">
      <StatusHero data={data} monitor={monitor} isAdmin={isAdmin} hasEmergencyDoc={hasEmergencyDoc} />

      <div className="start-line">
        <p className="start-quiet">
          <span><b>{counts.total}</b> Geräte</span>
          <span><b>{counts.online}</b> erreichbar</span>
          <span><b>{counts.critical}</b> wichtig</span>
          <span><b>{counts.accounts}</b> Zugänge</span>
          {data.lastScan && (
            <span title={new Date(data.lastScan.startedAt).toLocaleString("de-DE")}>
              Scan {when(data.lastScan.startedAt)}
              {data.lastScan.status === "failed" && <span className="start-bad"> (fehlgeschlagen)</span>}
              {data.lastScan.status === "running" && " (läuft)"}
            </span>
          )}
        </p>
        {!data.llmConfigured && isAdmin && (
          <Link to="/einstellungen" className="start-chip start-chip-link warn"
                title="Einstellungen → KI-Assistent: einen Anbieter wählen">
            <span className="dot" aria-hidden="true" />Assistent nicht eingerichtet · <u>Einrichten</u>
          </Link>
        )}
      </div>

      <div className="start-grid">
        <section aria-labelledby="start-critical">
          <h2 className="start-sec" id="start-critical">
            Wichtige Geräte
            <span className="start-sec-note">
              {data.monitorEnabled ? ` · live alle ${data.monitorIntervalSeconds} s` : " · Überwachung aus"}
            </span>
          </h2>
          {data.criticalSystems.length === 0 ? (
            <p className="start-empty">
              Noch kein Gerät als kritisch markiert. Geräte, ohne die im Haus etwas ausfällt, lassen
              sich in der Geräteansicht so kennzeichnen — sie werden dann automatisch laufend geprüft.
            </p>
          ) : (
            <ul className="start-list">
              {data.criticalSystems.map((s) => (
                <CriticalRow key={s.id} s={s} live={isLive(s)} monitor={monitor} />
              ))}
            </ul>
          )}
          {hiddenCritical > 0 && (
            // InventoryPage has no importance filter yet; this becomes /geraete?importance=critical
            // with the Geräte PR (redesign PR 3).
            <Link className="start-more" to="/geraete">+{hiddenCritical} weitere</Link>
          )}
          {/* Monitoring off: the hero says so and links to the settings, unless it is busy with
              an alarm or the empty inventory; then the hint stays here, as on the classic page. */}
          {!data.monitorEnabled && isAdmin && (anyDown || counts.total === 0) && (
            <p className="start-empty">
              Die Dauerüberwachung ist abgeschaltet. Einschalten unter{" "}
              <Link to="/einstellungen">Einstellungen → Überwachung</Link>.
            </p>
          )}
        </section>

        <div>
          <section aria-labelledby="start-quick">
            <h2 className="start-sec" id="start-quick">Schnell</h2>
            <div className="start-actions">
              <button type="button" className="secondary start-btn" onClick={() => void runInternetCheck()} disabled={checking}>
                {checking ? "Prüfe …" : "Internet prüfen"}
              </button>
              {isAdmin && <Link className="start-btn" to="/scan">Netzwerk scannen</Link>}
            </div>
            {check && (
              <div className={`start-check ${check.error ? "bad" : checkOk ? "ok" : "bad"}`} role="status">
                <span>{check.error || check.result?.explanation}</span>
                <span className="start-check-time">Geprüft {clock(check.at)}</span>
              </div>
            )}
          </section>
          <section aria-labelledby="start-kinds">
            <h2 className="start-sec" id="start-kinds">Was es im Netz gibt</h2>
            {kinds.length === 0 ? (
              <p className="start-empty">Noch keine Geräte erfasst.</p>
            ) : (
              <ul className="start-list">
                {kinds.map(([kind, count]) => (
                  <li key={kind}>
                    <Link to={`/geraete?kind=${kind}`} className="start-row start-row-kind">
                      <span className="start-row-name">{data.kindLabels[kind] ?? kind}</span>
                      <span className="start-count">{count}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

        </div>
      </div>
    </div>
  );
}
