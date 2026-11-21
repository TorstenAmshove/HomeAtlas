import { useCallback, useEffect, useState } from "react";
import { api, type AccessLogEntry } from "../../lib/api";
import { Skeleton } from "../../components/Skeleton";
import { useUrlState } from "../../lib/useUrlState";
import { fullDate, when } from "../device/common";
import { ACTION_LABEL, CRITICAL_ACTIONS } from "./accessLogLabels";
import "./mehr.css";

/**
 * "Protokoll" under Mehr in the new UI. Filters live in the URL (`?action=`, `?failures=1`), every row carries a status chip (fehlgeschlagen / sicherheitsrelevant / ok),
 * and a skeleton shows while it loads.
 */

export default function AccessLogPage() {
  const [action, setAction] = useUrlState("action");
  const [failuresParam, setFailures] = useUrlState("failures");
  const onlyFailures = failuresParam === "1";
  const [entries, setEntries] = useState<AccessLogEntry[] | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await api.accessLog({ limit: 300, action: action || undefined, onlyFailures });
      setEntries(r.entries);
      setActions(r.actions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [action, onlyFailures]);

  useEffect(() => { void load(); }, [load]);

  const failures = (entries ?? []).filter((e) => !e.ok).length;

  return (
    <div className="mehr-page log-page">
      <h1 className="visually-hidden">Zugriffsprotokoll</h1>
      <div className="m-toolbar">
        <label className="m-filter">
          <span className="visually-hidden">Vorgang</span>
          <select aria-label="Vorgang" value={action} onChange={(e) => setAction(e.target.value, { push: true })}>
            <option value="">Alle Vorgänge</option>
            {Array.from(new Set([...actions, ...(action ? [action] : [])])).map((a) => (
              <option key={a} value={a}>{ACTION_LABEL[a] ?? a}</option>
            ))}
          </select>
        </label>
        <button type="button" className="m-filter" aria-pressed={onlyFailures}
                onClick={() => setFailures(onlyFailures ? "" : "1", { push: true })}>
          Nur Fehlversuche
        </button>
        <button type="button" className="m-btn small" style={{ marginLeft: "auto" }} onClick={() => void load()} disabled={loading}>
          {loading ? "Lade …" : "Aktualisieren"}
        </button>
      </div>

      <p className="m-summary">
        Anmeldungen, Fehlversuche und alles, was an Benutzern oder gespeicherten Passwörtern verändert oder
        angesehen wurde; die letzten 5000 Einträge bleiben erhalten.
        {entries && failures > 0 && !onlyFailures && (
          <>
            {" "}<b>{failures}</b> {failures === 1 ? "Fehlversuch" : "Fehlversuche"} in dieser Ansicht ·{" "}
            <button type="button" className="m-link" onClick={() => setFailures("1", { push: true })}>nur diese zeigen</button>
          </>
        )}
      </p>

      {error && <div className="notice error" role="alert">{error}</div>}

      {entries === null || (loading && entries.length === 0) ? (
        <div role="status" aria-live="polite">
          <span className="visually-hidden">Wird geladen …</span>
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} className="m-skel-row">
              <div style={{ flex: 1, display: "grid", gap: 6 }}><Skeleton width={`${35 + ((i * 13) % 30)}%`} /><Skeleton width="25%" height={10} /></div>
              <Skeleton width={90} height={12} />
            </div>
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div className="m-empty">
          <p>Keine Einträge für diese Auswahl.</p>
          {(action || onlyFailures) && (
            <button type="button" className="m-btn" onClick={() => { setAction(""); setFailures(""); }}>Filter zurücksetzen</button>
          )}
        </div>
      ) : (
        <ul className="m-rows" aria-label="Protokolleinträge" aria-busy={loading}>
          {entries.map((e) => {
            const tone = !e.ok ? "bad" : CRITICAL_ACTIONS.has(e.action) ? "warn" : "ok";
            const word = !e.ok ? "fehlgeschlagen" : CRITICAL_ACTIONS.has(e.action) ? "sicherheitsrelevant" : "ok";
            return (
              <li key={e.id} className="m-row" data-testid="log-row">
                <div className="m-row-main">
                  <span className="m-row-title">
                    <span className="m-row-name">{ACTION_LABEL[e.action] ?? e.action}</span>
                    <span className={`m-chip ${tone}`}><span className="dot" aria-hidden="true" />{word}</span>
                  </span>
                  <span className="m-row-sub">
                    {e.username || "unbekannter Benutzer"}
                    {e.detail && <> · {e.detail}</>}
                  </span>
                  <span className="m-row-sub" title={e.userAgent || undefined}>
                    <span className="mono">{e.ip || "—"}</span>
                    {e.userAgent && <> · {e.userAgent.length > 80 ? `${e.userAgent.slice(0, 80)} …` : e.userAgent}</>}
                  </span>
                </div>
                <span className="m-row-time" title={fullDate(e.at)}>{when(e.at)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
