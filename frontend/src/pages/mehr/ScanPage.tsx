import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Scan } from "../../lib/api";
import { Skeleton } from "../../components/Skeleton";
import { fullDate, when } from "../device/common";
import "./mehr.css";

/**
 * "Scan" under Mehr in the new UI. Summary first: what is running (phase and progress) or how the
 * last scan ended, with one line "Was ist neu?" built only from numbers the scan summary already
 * carries (`created`, `updated`, `devicesFound`; pipeline.py), then the history.
 * Polling rule: only while a scan runs, and only while the tab is visible.
 */

const STATUS_WORD: Record<Scan["status"], string> = { running: "läuft", completed: "fertig", failed: "fehlgeschlagen" };
const STATUS_TONE: Record<Scan["status"], string> = { running: "", completed: "ok", failed: "bad" };

function n(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export default function ScanPage() {
  const [scan, setScan] = useState<Scan | null>(null);
  const [history, setHistory] = useState<Scan[] | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    try {
      const { scans, running } = await api.listScans();
      setHistory(scans);
      const active = running ?? (scans.length > 0 ? (await api.getScan(scans[0].id)).scan : null);
      setScan(active);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setHistory((h) => h ?? []);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const running = scan?.status === "running";
  useEffect(() => {
    if (!running || !scan) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void api.getScan(scan.id).then((r) => {
        setScan(r.scan);
        if (r.scan.status !== "running") void load();
      }).catch(() => {});
    }, 1500);
    return () => window.clearInterval(timer);
  }, [running, scan?.id, load]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setStarting(true);
    setError("");
    try {
      const { scanId } = await api.startScan();
      setScan((await api.getScan(scanId)).scan);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  if (history === null) {
    return (
      <div className="mehr-page scan-page" role="status" aria-live="polite">
        <span className="visually-hidden">Wird geladen …</span>
        <div className="scan-hero"><div style={{ display: "grid", gap: 8, flex: 1 }}><Skeleton width={220} height={20} /><Skeleton width="50%" /></div><Skeleton width={130} height={40} radius={8} /></div>
        <Skeleton width="70%" />
        <Skeleton width={120} height={12} style={{ margin: "26px 0 10px" }} />
        {Array.from({ length: 4 }, (_, i) => <div key={i} className="m-skel-row"><Skeleton width="40%" /><Skeleton width={70} height={12} /></div>)}
      </div>
    );
  }

  const summary = scan?.summary ?? null;
  const warnings: string[] = summary?.warnings ?? [];
  const earlier = history.filter((s) => s.id !== scan?.id);
  const startButton = (
    <button type="button" className="m-btn primary" onClick={() => void start()} disabled={starting || running}>
      {running ? "Scan läuft …" : starting ? "Starte …" : "Scan starten"}
    </button>
  );

  return (
    <div className="mehr-page scan-page">
      <h1 className="visually-hidden">Netzwerk-Scan</h1>
      {error && <div className="notice error" role="alert">{error}</div>}

      {!scan ? (
        <div className="m-empty">
          <h2>Noch kein Scan</h2>
          <p>
            HomeAtlas sucht die Geräte im Heimnetz, erkennt ihre Dienste, fragt Docker und eingerichtete
            Controller ab und schreibt danach die Dokumentation neu. Ein Durchlauf dauert je nach Netzgröße
            einige Minuten.
          </p>
          {startButton}
        </div>
      ) : (
        <>
          <section className="scan-hero" aria-labelledby="scan-hero-title">
            <div>
              <h2 id="scan-hero-title">
                {running ? scan.phase || "Scan läuft …" : scan.status === "completed" ? "Letzter Scan abgeschlossen" : "Letzter Scan fehlgeschlagen"}
              </h2>
              <p title={fullDate(scan.startedAt)}>
                <span className={`m-chip ${STATUS_TONE[scan.status]}`}><span className="dot" aria-hidden="true" />{STATUS_WORD[scan.status]}</span>
                {" · gestartet "}{when(scan.startedAt)}
                {scan.subnets && <> · <span className="mono">{scan.subnets}</span></>}
              </p>
            </div>
            {startButton}
          </section>

          {running && (
            <div role="progressbar" aria-label="Fortschritt des Scans" aria-valuenow={scan.progress} aria-valuemin={0} aria-valuemax={100}>
              <div className="scan-bar"><div style={{ width: `${scan.progress}%` }} /></div>
              <p className="m-quiet">{scan.progress} % · aktualisiert sich, solange diese Seite offen ist</p>
            </div>
          )}

          {!running && scan.status === "completed" && summary && (
            <p className="scan-new" data-testid="scan-new">
              Was ist neu? <b>{n(summary.created)}</b> {n(summary.created) === 1 ? "neues Gerät" : "neue Geräte"} ·{" "}
              <b>{n(summary.updated)}</b> aktualisiert · <b>{n(summary.devicesFound)}</b> gefunden
              {summary.gateway ? <> · Router <span className="mono">{summary.gateway}</span></> : null}
              {n(summary.created) > 0 && <> · <Link to="/geraete">Zur Geräteliste</Link></>}
            </p>
          )}

          {summary?.error && <div className="notice error" role="alert">{summary.error}</div>}

          {warnings.length > 0 && (
            <>
              <h2 className="m-sec">Hinweise</h2>
              <ul className="m-dialog-list" style={{ maxWidth: "80ch" }}>
                {warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </>
          )}

          {scan.log && (
            <details className="scan-log">
              <summary>Ausführliches Protokoll</summary>
              <pre className="mono" tabIndex={0}>{scan.log}</pre>
            </details>
          )}
        </>
      )}

      {earlier.length > 0 && (
        <>
          <h2 className="m-sec">Frühere Scans</h2>
          <ul className="m-rows" aria-label="Frühere Scans">
            {earlier.map((s) => (
              <li key={s.id} className="m-row">
                <div className="m-row-main">
                  <span className="m-row-name" title={fullDate(s.startedAt)}>{when(s.startedAt)}</span>
                  <span className="m-row-sub mono">{s.subnets || "—"}</span>
                </div>
                <div className="m-row-side">
                  <span className="m-row-time">{s.summary?.devicesFound != null ? `${s.summary.devicesFound} Geräte` : "—"}</span>
                  <span className={`m-chip ${STATUS_TONE[s.status]}`}><span className="dot" aria-hidden="true" />{STATUS_WORD[s.status]}</span>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
