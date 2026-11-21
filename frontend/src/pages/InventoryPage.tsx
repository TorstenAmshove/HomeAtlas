import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, DUPLICATE_REASON_LABEL, type DuplicateCandidate, type System } from "../lib/api";
import { useAuth } from "../App";
import { KindIcon } from "../lib/icons";
import { useUi } from "../shell/ui";
import { useUrlState } from "../lib/useUrlState";
import InventoryCalm from "./geraete/InventoryCalm";
import {
  IMPORTANCE_LABEL, STATUS_LABEL, formatSort, groupByProject, matchesFilter, nextSort, parseSort, projectOf, readFilter,
  sortSystems, type SortKey,
} from "./geraete/inventoryModel";

/** The new UI has its own component (pages/geraete/InventoryCalm.tsx). With the switch off the
 *  classic page below renders as before, except that search and sort now live in the URL as well
 *  (forensics "Geräte" 2: Back must not lose the search) and `?status=`/`?importance=` filter. */
export default function InventoryPage() {
  const { calm } = useUi();
  return calm ? <InventoryCalm /> : <InventoryClassic />;
}

function InventoryClassic() {
  const { isAdmin } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [systems, setSystems] = useState<System[]>([]);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [query, setQuery] = useUrlState("q");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // No `?sort=` = "unsorted" -- the order the API already returns (critical devices first, see
  // db.list_systems), which a column sort deliberately overrides until reset again.
  const [sortParam, setSortParam] = useUrlState("sort");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const sort = parseSort(sortParam);

  function toggleSort(key: SortKey) {
    setSortParam(formatSort(nextSort(sort, key)));
  }

  function sortIndicator(key: SortKey) {
    if (!sort || sort.key !== key) return "";
    return sort.dir === "asc" ? " ▲" : " ▼";
  }

  const { kind, parentId, project, status, importance } = readFilter(searchParams);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  function setParam(name: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(name, value); else next.delete(name);
    setSearchParams(next);
  }

  function toggleCollapsed(name: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }

  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([]);

  function reloadCandidates() {
    if (!isAdmin) return;
    api.getDuplicateCandidates().then((r) => setCandidates(r.candidates)).catch(() => setCandidates([]));
  }

  async function notDuplicate(c: DuplicateCandidate) {
    try {
      await api.markNotDuplicate(c.aId, c.bId);
      reloadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function keepAndMerge(c: DuplicateCandidate, keepId: string) {
    await mergeSelected(keepId, keepId === c.aId ? c.bId : c.aId);
    reloadCandidates();
  }

  useEffect(reloadCandidates, [isAdmin]);

  useEffect(() => {
    setLoading(true);
    api
      .listSystems()
      .then((r) => {
        setSystems(r.systems);
        setKindLabels(r.kindLabels);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const visible = useMemo(() => sortSystems(
    systems.filter((s) => matchesFilter(s, { q: query, kind, parentId, project, status, importance, subnet: "" })),
    parseSort(sortParam),
    kindLabels,
  ), [systems, kind, parentId, project, status, importance, query, sortParam, kindLabels]);

  function toggleSelected(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAllVisible() {
    setSelected((current) => {
      const allSelected = visible.length > 0 && visible.every((s) => current.has(s.id));
      if (allSelected) return new Set();
      return new Set(visible.map((s) => s.id));
    });
  }

  async function deleteSelected() {
    if (selected.size === 0) return;
    if (!window.confirm(`${selected.size} Gerät${selected.size === 1 ? "" : "e"} wirklich löschen?`)) return;
    setBulkBusy(true);
    const ids = [...selected];
    // allSettled, not all -- one failing delete (a stale row already gone server-side, a timeout)
    // must not stop the successful ones from being reflected in the UI.
    const results = await Promise.allSettled(ids.map((id) => api.deleteSystem(id)));
    const deletedIds = new Set(ids.filter((_, i) => results[i].status === "fulfilled"));
    if (deletedIds.size > 0) {
      setSystems((current) => current.filter((s) => !deletedIds.has(s.id)));
      setSelected((current) => {
        const next = new Set(current);
        deletedIds.forEach((id) => next.delete(id));
        return next;
      });
    }
    const failedCount = results.length - deletedIds.size;
    setError(failedCount > 0
      ? `${failedCount} Gerät${failedCount === 1 ? "" : "e"} konnten nicht gelöscht werden.`
      : "");
    setBulkBusy(false);
  }

  async function mergeSelected(keepId: string, removeId: string) {
    const keep = systems.find((s) => s.id === keepId);
    const remove = systems.find((s) => s.id === removeId);
    if (!window.confirm(
      `„${remove?.name}" wird gelöscht, seine Zugänge und Historie werden zu „${keep?.name}" ` +
      "übernommen (leere Felder von dort werden ebenfalls übernommen). Fortfahren?",
    )) return;
    setBulkBusy(true);
    try {
      const { system } = await api.mergeSystems(keepId, removeId);
      setSystems((current) => current.filter((s) => s.id !== removeId).map((s) => (s.id === keepId ? system : s)));
      setSelected(new Set());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBulkBusy(false);
    }
  }

  const selectedList = useMemo(() => systems.filter((s) => selected.has(s.id)), [systems, selected]);

  const parentSystem = useMemo(
    () => (parentId ? systems.find((s) => s.id === parentId) : undefined),
    [systems, parentId],
  );

  const kinds = useMemo(
    () => Array.from(new Set(systems.map((s) => s.kind))).sort(),
    [systems],
  );

  const projects = useMemo(
    () => Array.from(new Set(systems.map(projectOf).filter(Boolean))).sort((a, b) => a.localeCompare(b)),
    [systems],
  );

  const groups = useMemo(() => groupByProject(visible), [visible]);

  async function addSystem() {
    const name = window.prompt("Wie soll das neue Gerät heißen?");
    if (!name?.trim()) return;
    try {
      const { system } = await api.createSystem({ name: name.trim(), kind: "other" });
      setSystems((current) => [system, ...current]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function renderRow(s: System) {
    return (
      <tr key={s.id}>
        {isAdmin && (
          <td>
            <input type="checkbox" style={{ width: "auto" }} checked={selected.has(s.id)}
                   onChange={() => toggleSelected(s.id)} />
          </td>
        )}
        <td>
          <Link to={`/geraete/${s.id}`}>
            <strong>{s.name}</strong>
          </Link>
          {s.importance === "critical" && (
            <span className="badge warn" style={{ marginLeft: 8 }}>kritisch</span>
          )}
          {!!s.errorCount && (
            <span className="badge danger" style={{ marginLeft: 8 }}
                  title={`${s.errorCount} protokollierte(r) Fehler -- siehe Geräteseite`}>
              ⚠ {s.errorCount}
            </span>
          )}
          {(s.tags ?? []).some((t) => t.toLowerCase().includes("poe")) && (
            <span className="badge warn" style={{ marginLeft: 8 }}
                  title="Funktioniert ohne PoE-fähigen Switch oder Injector nicht">
              ⚡ PoE
            </span>
          )}
          {s.purpose && (
            <div className="muted" style={{ fontSize: "0.83rem" }}>{s.purpose}</div>
          )}
        </td>
        <td className="mono">
          {s.ip || "—"}
          {s.hostname && <div className="muted" style={{ fontSize: "0.8rem" }}>{s.hostname.split(".")[0]}</div>}
        </td>
        <td>
          <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
            <KindIcon kind={s.kind} className="muted" />
            {kindLabels[s.kind] ?? s.kind}
          </span>
        </td>
        <td>{s.location || "—"}</td>
        <td>
          <span className={`badge ${s.status === "online" ? "ok" : s.status === "offline" ? "danger" : ""}`}>
            {STATUS_LABEL[s.status] ?? s.status}
          </span>
        </td>
      </tr>
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Geräte</h1>
          <p>
            Alles, was im Heimnetz gefunden oder von Hand eingetragen wurde. Selbst gepflegte Angaben
            bleiben bei künftigen Scans erhalten.
          </p>
        </div>
        {isAdmin && <button onClick={() => void addSystem()}>+ Gerät anlegen</button>}
      </div>

      {error && <div className="notice error">{error}</div>}

      {isAdmin && candidates.length > 0 && (
        <div className="notice info">
          <strong>Doppelt? {candidates.length} Verdachtsfälle</strong> – zusammengeführt wird nur nach deiner Bestätigung.
          {candidates.map((c) => (
            <div key={`${c.aId}-${c.bId}`} className="row" style={{ marginTop: 8 }}>
              <span>
                „{c.aName}" und „{c.bName}" ({c.reasons.map((r) => DUPLICATE_REASON_LABEL[r]).join(", ")})
              </span>
              <button className="secondary" disabled={bulkBusy} onClick={() => void keepAndMerge(c, c.aId)}>
                Behalte {c.aName}
              </button>
              <button className="secondary" disabled={bulkBusy} onClick={() => void keepAndMerge(c, c.bId)}>
                Behalte {c.bName}
              </button>
              <button className="secondary" disabled={bulkBusy} onClick={() => void notDuplicate(c)}>
                Kein Duplikat
              </button>
            </div>
          ))}
        </div>
      )}

      {(status || importance) && (
        // Set by links from the new UI (Start → "+N weitere" → ?importance=critical); the classic
        // page has no controls for them, so it says what is filtered and offers the way out.
        <div className="notice info">
          Gefiltert nach{" "}
          {[status && `Zustand „${STATUS_LABEL[status] ?? status}“`,
            importance && `Bedeutung „${IMPORTANCE_LABEL[importance] ?? importance}“`].filter(Boolean).join(" und ")}.
          <button className="secondary" style={{ marginLeft: 8 }} onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.delete("status");
            next.delete("importance");
            setSearchParams(next);
          }}>
            Filter aufheben
          </button>
        </div>
      )}

      {parentId && (
        <div className="notice info">
          Zeigt Container und VMs auf <strong>{parentSystem?.name ?? "diesem Host"}</strong>.{" "}
          <button className="secondary" style={{ marginLeft: 8 }} onClick={() => setSearchParams({})}>
            Filter aufheben
          </button>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ marginBottom: 14 }}>
          <input
            style={{ flex: 1, minWidth: 220 }}
            placeholder="Suchen nach Name, IP, Hersteller, Raum …"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            style={{ width: "auto" }}
            value={kind}
            onChange={(e) => setParam("kind", e.target.value)}
          >
            <option value="">Alle Kategorien</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {kindLabels[k] ?? k}
              </option>
            ))}
          </select>
          {projects.length > 0 && (
            <select style={{ width: "auto" }} value={project} onChange={(e) => setParam("project", e.target.value)}>
              <option value="">Alle Compose-Projekte</option>
              {projects.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          )}
        </div>

        {isAdmin && selected.size > 0 && (
          <div className="row notice info" style={{ marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
            <strong>{selected.size}</strong> ausgewählt
            {selected.size === 2 && (
              <span className="row" style={{ gap: 6, alignItems: "center" }}>
                <span className="muted">— dasselbe Gerät doppelt? Zusammenführen, behalte:</span>
                {selectedList.map((s) => {
                  const other = selectedList.find((o) => o.id !== s.id);
                  if (!other) return null;
                  return (
                    <button key={s.id} className="secondary" disabled={bulkBusy}
                            onClick={() => void mergeSelected(s.id, other.id)}>
                      „{s.name}"
                    </button>
                  );
                })}
              </span>
            )}
            <button className="danger" style={{ marginLeft: "auto" }} disabled={bulkBusy}
                    onClick={() => void deleteSelected()}>
              {bulkBusy ? "Lösche…" : "Ausgewählte löschen"}
            </button>
            <button className="secondary" onClick={() => setSelected(new Set())} disabled={bulkBusy}>
              Auswahl aufheben
            </button>
          </div>
        )}

        {loading ? (
          <span className="spinner" />
        ) : visible.length === 0 ? (
          <p className="muted">
            Keine Geräte gefunden.{" "}
            {systems.length === 0 && isAdmin && (
              <>
                Starte einen <Link to="/scan">Netzwerk-Scan</Link>, um das Heimnetz automatisch zu erfassen.
              </>
            )}
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {isAdmin && (
                    <th style={{ width: 1 }}>
                      <input type="checkbox" style={{ width: "auto" }}
                             checked={visible.length > 0 && visible.every((s) => selected.has(s.id))}
                             onChange={toggleSelectAllVisible} />
                    </th>
                  )}
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("name")}>Gerät{sortIndicator("name")}</th>
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("ip")}>Adresse{sortIndicator("ip")}</th>
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("kind")}>Art{sortIndicator("kind")}</th>
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("location")}>Standort{sortIndicator("location")}</th>
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("status")}>Zustand{sortIndicator("status")}</th>
                </tr>
              </thead>
              <tbody>
                {groups.loose.map(renderRow)}
                {groups.stacks.map((g) => (
                  <Fragment key={`stack:${g.name}`}>
                    <tr style={{ cursor: "pointer" }} onClick={() => toggleCollapsed(g.name)}>
                      <td colSpan={isAdmin ? 6 : 5} style={{ background: "var(--surface-2, rgba(128,128,128,0.08))" }}>
                        <strong>{collapsed.has(g.name) ? "▸" : "▾"} Compose: {g.name}</strong>{" "}
                        <span className="muted">({g.items.length} Container)</span>
                      </td>
                    </tr>
                    {!collapsed.has(g.name) && g.items.map(renderRow)}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
