import { useCallback, useEffect, useState } from "react";
import { api, DUPLICATE_REASON_LABEL, type DuplicateCandidate, type System, type SystemAlias } from "../lib/api";

/** Admin-only: "Weitere IPs", the "Doppelt?" hint for this device and the manual merge. This
 *  device is always the one that is kept. Nothing here merges without a click and a confirmation. */
export default function MergePanel({ system, onMerged }: { system: System; onMerged: () => void }) {
  const [aliases, setAliases] = useState<SystemAlias[]>([]);
  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([]);
  const [others, setOthers] = useState<System[]>([]);
  const [picking, setPicking] = useState(false);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(() => {
    api.getSystemAliases(system.id).then((r) => setAliases(r.aliases)).catch(() => setAliases([]));
    api.getDuplicateCandidates()
      .then((r) => setCandidates(r.candidates.filter((c) => c.aId === system.id || c.bId === system.id)))
      .catch(() => setCandidates([]));
  }, [system.id]);

  useEffect(reload, [reload]);

  async function startPicking() {
    setPicking(true);
    setChoice("");
    try {
      const r = await api.listSystems();
      setOthers(r.systems.filter((s) => s.id !== system.id)
        .sort((a, b) => a.name.localeCompare(b.name, "de")));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function merge(removeId: string, removeName: string) {
    if (!window.confirm(
      `„${removeName}" wird gelöscht, seine Zugänge und Historie werden zu „${system.name}" ` +
      "übernommen (leere Felder von dort werden ebenfalls übernommen). Fortfahren?",
    )) return;
    setBusy(true);
    try {
      await api.mergeSystems(system.id, removeId);
      setError("");
      setPicking(false);
      onMerged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function notDuplicate(otherId: string) {
    setBusy(true);
    try {
      await api.markNotDuplicate(system.id, otherId);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const extraIps = Array.from(new Set(aliases.map((a) => a.ip).filter((ip) => ip && ip !== system.ip)));
  const extraMacs = Array.from(new Set(aliases.map((a) => a.mac).filter((m) => m && m !== system.mac)));

  return (
    <>
      {error && <div className="notice error">{error}</div>}
      {candidates.map((c) => {
        const otherId = c.aId === system.id ? c.bId : c.aId;
        const otherName = c.aId === system.id ? c.bName : c.aName;
        return (
          <div key={otherId} className="notice info">
            Doppelt? „{otherName}" ({c.reasons.map((r) => DUPLICATE_REASON_LABEL[r]).join(", ")}).{" "}
            <button className="secondary" disabled={busy} onClick={() => void merge(otherId, otherName)}>
              Zusammenführen
            </button>{" "}
            <button className="secondary" disabled={busy} onClick={() => void notDuplicate(otherId)}>
              Kein Duplikat
            </button>
          </div>
        );
      })}
      {(extraIps.length > 0 || extraMacs.length > 0) && (
        <p className="muted">
          Weitere IPs: {extraIps.join(", ") || "–"}
          {extraMacs.length > 0 && <> · Weitere MACs: {extraMacs.join(", ")}</>}
        </p>
      )}
      {picking ? (
        <div className="row" style={{ marginBottom: 12 }}>
          <select style={{ width: "auto" }} value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">Duplikat wählen …</option>
            {others.map((s) => (
              <option key={s.id} value={s.id}>{s.name}{s.ip ? ` (${s.ip})` : ""}</option>
            ))}
          </select>
          <button className="secondary" disabled={!choice || busy}
                  onClick={() => void merge(choice, others.find((s) => s.id === choice)?.name ?? "")}>
            Zusammenführen
          </button>
          <button className="secondary" onClick={() => setPicking(false)}>Abbrechen</button>
        </div>
      ) : (
        <div style={{ marginBottom: 12 }}>
          <button className="secondary" onClick={() => void startPicking()}>Zusammenführen…</button>
        </div>
      )}
    </>
  );
}
