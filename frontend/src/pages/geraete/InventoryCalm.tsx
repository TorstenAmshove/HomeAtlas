import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, DUPLICATE_REASON_LABEL, type DuplicateCandidate, type System } from "../../lib/api";
import { useAuth } from "../../App";
import ConfirmDialog from "../../components/ConfirmDialog";
import { Skeleton } from "../../components/Skeleton";
import {
  IMPORTANCE_LABEL, STATUS_LABEL, groupByProject, matchesFilter, parseSort, projectOf, readFilter, sortSystems,
} from "./inventoryModel";
import "./geraete.css";

/**
 * Device list of the redesigned UI (docs/redesign/5-information-architecture.md, area "Geräte",
 * tab "Liste"), shown instead of the classic InventoryPage while `uiCalm` is on.
 *
 * Everything that decides what the list shows is in the URL (`q`, `sort`, `status`, `importance`,
 * `kind`, `project`, `parentId`, plus `duplikate=1` for the review panel), so opening a device and
 * coming Back lands on exactly the same list (forensics "Geräte" 2).
 *
 * Numbers (docs/redesign/3-numbers-audit.md): every count is computed from the one
 * `GET /api/systems` list over the whole inventory, the same way the classic filter works --
 * "Alle" = all rows (= dashboard `counts.total`), "Nicht erreichbar" = status 'offline'
 * (= `counts.offline`, every device, not only the monitored ones the Start alarm uses, B3),
 * "Wichtig" = importance 'critical' (= `counts.critical`). Duplicates = length of
 * `GET /api/systems/duplicates`.
 */

const COLLAPSED_KEY = "homeatlas.geraete.collapsed";

function readCollapsed(): Set<string> {
  try {
    const raw = window.sessionStorage.getItem(COLLAPSED_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((x) => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function writeCollapsed(value: Set<string>) {
  try {
    window.sessionStorage.setItem(COLLAPSED_KEY, JSON.stringify([...value]));
  } catch {
    // Storage blocked: the groups just open again next time.
  }
}

const SORT_OPTIONS: [string, string][] = [
  ["", "Wichtige zuerst"],
  ["name", "Name A–Z"],
  ["-name", "Name Z–A"],
  ["ip", "Adresse"],
  ["kind", "Art"],
  ["location", "Standort"],
  ["-status", "Nicht erreichbare zuerst"],
  ["status", "Erreichbare zuerst"],
];

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

type Pending =
  | { kind: "delete"; ids: string[] }
  | { kind: "merge"; keepId: string; removeId: string; keepName: string; removeName: string };

function StatusChip({ status }: { status: System["status"] }) {
  const cls = status === "online" ? "ok" : status === "offline" ? "bad" : "";
  const label = STATUS_LABEL[status] ?? status;
  return (
    <span className={`geraete-chip ${cls}`}>
      <span className="dot" aria-hidden="true" />
      <span className="inv-status-long">{label}</span>
      {/* Phone: a dot is enough for "erreichbar"; anything else says so in one word. */}
      <span className="inv-status-short">
        {status === "online" ? <span className="visually-hidden">{label}</span> : status === "offline" ? "aus" : "?"}
      </span>
    </span>
  );
}

function ListSkeleton() {
  return (
    <div role="status" aria-live="polite">
      <span className="visually-hidden">Wird geladen …</span>
      <div className="inv-toolbar">
        <Skeleton width="100%" height={40} radius={8} />
      </div>
      <div className="inv-chips">
        {[64, 120, 80, 60].map((w, i) => <Skeleton key={i} width={w} height={14} />)}
      </div>
      <ul className="inv-list">
        {Array.from({ length: 8 }, (_, i) => (
          <li key={i} className="inv-row inv-row-skeleton">
            <div style={{ flex: 1, display: "grid", gap: 6 }}>
              <Skeleton width={`${45 + ((i * 17) % 35)}%`} />
              <Skeleton width="30%" height={10} />
            </div>
            <Skeleton width={84} height={12} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function AddDeviceDialog({ open, kindLabels, onCancel, onCreated }: {
  open: boolean;
  kindLabels: Record<string, string>;
  onCancel: () => void;
  onCreated: (system: System) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("other");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return;
    setName("");
    setKind("other");
    setError("");
    const previouslyFocused = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCancelRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const kinds = Object.entries(kindLabels).sort((a, b) => a[1].localeCompare(b[1], "de"));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Bitte einen Namen eingeben.");
      inputRef.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { system } = await api.createSystem({ name: trimmed, kind });
      onCreated(system);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
      <form className="dialog inv-add" role="dialog" aria-modal="true" aria-labelledby="inv-add-title"
            onSubmit={(e) => void submit(e)} noValidate>
        <h2 id="inv-add-title">Gerät von Hand anlegen</h2>
        <p className="dialog-lead">
          Für Geräte, die kein Scan findet. Weitere Angaben trägst du danach auf der Geräteseite ein.
        </p>
        <label className="inv-field">
          <span>Name</span>
          <input ref={inputRef} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off"
                 placeholder="z. B. Heizung Keller" aria-invalid={Boolean(error) || undefined} />
        </label>
        <label className="inv-field">
          <span>Art</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {kinds.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        {error && <p className="inv-field-error" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Abbrechen</button>
          <button type="submit" disabled={busy}>{busy ? "Bitte warten …" : "Anlegen und öffnen"}</button>
        </div>
      </form>
    </div>
  );
}

export default function InventoryCalm() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filter = readFilter(params);
  const sortParam = params.get("sort") ?? "";
  const reviewOpen = isAdmin && params.get("duplikate") === "1";

  const [systems, setSystems] = useState<System[] | null>(null);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([]);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [adding, setAdding] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(readCollapsed);

  /** Changes some URL parameters; "" removes one. Replaces the history entry, so Back still
   *  leaves the list (and coming back restores it) instead of stepping through every filter. */
  const update = useCallback((changes: Record<string, string>, push = false) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value) next.set(key, value); else next.delete(key);
      }
      return next;
    }, { replace: !push });
  }, [setParams]);

  const reloadCandidates = useCallback(() => {
    if (!isAdmin) return;
    api.getDuplicateCandidates().then((r) => setCandidates(r.candidates)).catch(() => setCandidates([]));
  }, [isAdmin]);

  useEffect(reloadCandidates, [reloadCandidates]);

  useEffect(() => {
    api.listSystems()
      .then((r) => {
        setSystems(r.systems);
        setKindLabels(r.kindLabels);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const all = useMemo(() => systems ?? [], [systems]);
  const visible = useMemo(
    () => {
      const current = readFilter(params);
      return sortSystems(all.filter((s) => matchesFilter(s, current)), parseSort(params.get("sort") ?? ""), kindLabels);
    },
    [all, params, kindLabels],
  );
  const groups = useMemo(() => groupByProject(visible), [visible]);

  const counts = useMemo(() => ({
    total: all.length,
    offline: all.filter((s) => s.status === "offline").length,
    critical: all.filter((s) => s.importance === "critical").length,
  }), [all]);

  const kindCounts = useMemo(() => {
    const map = new Map<string, number>();
    all.forEach((s) => map.set(s.kind, (map.get(s.kind) ?? 0) + 1));
    return [...map.entries()].sort((a, b) => (kindLabels[a[0]] ?? a[0]).localeCompare(kindLabels[b[0]] ?? b[0], "de"));
  }, [all, kindLabels]);

  const projects = useMemo(
    () => Array.from(new Set(all.map(projectOf).filter(Boolean))).sort((a, b) => a.localeCompare(b)),
    [all],
  );

  const byId = useMemo(() => new Map(all.map((s) => [s.id, s])), [all]);
  const anyFilter = Boolean(filter.kind || filter.project || filter.parentId || filter.status || filter.importance);

  function clearFilters() {
    update({ kind: "", project: "", parentId: "", status: "", importance: "", q: "" });
  }

  function toggleCollapsed(name: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name); else next.add(name);
      writeCollapsed(next);
      return next;
    });
  }

  function toggleSelected(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  const allVisibleSelected = visible.length > 0 && visible.every((s) => selected.has(s.id));

  function stopSelecting() {
    setSelecting(false);
    setSelected(new Set());
  }

  async function runDelete(ids: string[]) {
    setBusy(true);
    // allSettled, not all -- one failing delete (a stale row already gone server-side, a timeout)
    // must not stop the successful ones from being reflected in the UI.
    const results = await Promise.allSettled(ids.map((id) => api.deleteSystem(id)));
    const deleted = new Set(ids.filter((_, i) => results[i].status === "fulfilled"));
    setSystems((current) => (current ?? []).filter((s) => !deleted.has(s.id))
      .map((s) => (s.parentId && deleted.has(s.parentId) ? { ...s, parentId: null } : s)));
    setSelected((current) => new Set([...current].filter((id) => !deleted.has(id))));
    const failed = ids.length - deleted.size;
    setError(failed > 0 ? `${plural(failed, "Gerät konnte", "Geräte konnten")} nicht gelöscht werden.` : "");
    setNotice(deleted.size > 0 ? `${plural(deleted.size, "Gerät", "Geräte")} gelöscht.` : "");
    if (failed === 0) setSelecting(false);
    setBusy(false);
    setPending(null);
    reloadCandidates();
  }

  async function runMerge(keepId: string, removeId: string) {
    setBusy(true);
    try {
      const { system } = await api.mergeSystems(keepId, removeId);
      setSystems((current) => (current ?? []).filter((s) => s.id !== removeId).map((s) => (s.id === keepId ? system : s)));
      setSelected(new Set());
      setSelecting(false);
      setError("");
      setNotice(`Zusammengeführt zu „${system.name}“.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setPending(null);
      reloadCandidates();
    }
  }

  async function notDuplicate(c: DuplicateCandidate) {
    setBusy(true);
    try {
      await api.markNotDuplicate(c.aId, c.bId);
      setNotice(`„${c.aName}“ und „${c.bName}“ werden nicht mehr als Duplikat vorgeschlagen.`);
      reloadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function askMerge(keepId: string, removeId: string, keepName: string, removeName: string) {
    setPending({ kind: "merge", keepId, removeId, keepName, removeName });
  }

  // --- the review dialog's consequences

  let dialog: ReactNode = null;
  if (pending?.kind === "delete") {
    const doomed = pending.ids.map((id) => byId.get(id)).filter((s): s is System => Boolean(s));
    const accounts = doomed.reduce((sum, s) => sum + (s.accountCount ?? 0), 0);
    const doomedIds = new Set(doomed.map((s) => s.id));
    const orphans = all.filter((s) => s.parentId && doomedIds.has(s.parentId) && !doomedIds.has(s.id)).length;
    const shown = doomed.slice(0, 12);
    const consequences: ReactNode[] = [
      <>
        {doomed.length === 1 ? "Dieses Gerät wird gelöscht:" : `Diese ${doomed.length} Geräte werden gelöscht:`}
        <ul className="inv-doomed">
          {shown.map((s) => <li key={s.id}>{s.name}{s.ip ? <span className="muted"> · {s.ip}</span> : null}</li>)}
          {doomed.length > shown.length && <li className="muted">… und {doomed.length - shown.length} weitere</li>}
        </ul>
      </>,
    ];
    if (accounts > 0) {
      consequences.push(<>{plural(accounts, "hinterlegter Zugang wird", "hinterlegte Zugänge werden")} mitgelöscht, samt Passwort.</>);
    }
    if (orphans > 0) {
      consequences.push(<>{plural(orphans, "Container oder VM verliert", "Container und VMs verlieren")} die Zuordnung zum Host.</>);
    }
    consequences.push(<>Selbst gepflegte Angaben, Notizen und Verlauf dieser Geräte sind weg. Ein späterer Scan legt gefundene Geräte neu an, aber ohne sie.</>);
    dialog = (
      <ConfirmDialog
        open
        danger
        busy={busy}
        title={doomed.length === 1 ? `„${doomed[0]?.name}“ löschen?` : `${doomed.length} Geräte löschen?`}
        consequences={consequences}
        confirmLabel={doomed.length === 1 ? "Gerät löschen" : `${doomed.length} Geräte löschen`}
        onConfirm={() => runDelete(doomed.map((s) => s.id))}
        onCancel={() => setPending(null)}
      >
        <p className="dialog-lead">Das lässt sich nicht rückgängig machen.</p>
      </ConfirmDialog>
    );
  } else if (pending?.kind === "merge") {
    dialog = (
      <ConfirmDialog
        open
        busy={busy}
        title="Zusammenführen?"
        consequences={[
          <>„{pending.removeName}“ wird gelöscht.</>,
          <>Seine Zugänge und sein Verlauf gehen auf „{pending.keepName}“ über.</>,
          <>Felder, die bei „{pending.keepName}“ leer sind, werden von „{pending.removeName}“ übernommen.</>,
        ]}
        confirmLabel={`Zu „${pending.keepName}“ zusammenführen`}
        onConfirm={() => runMerge(pending.keepId, pending.removeId)}
        onCancel={() => setPending(null)}
      >
        <p className="dialog-lead">Das lässt sich nicht rückgängig machen.</p>
      </ConfirmDialog>
    );
  }

  if (error && systems === null) return <div className="geraete-calm"><div className="notice error">{error}</div></div>;
  if (systems === null) return <div className="geraete-calm"><ListSkeleton /></div>;

  const selectedList = all.filter((s) => selected.has(s.id));
  const parentSystem = filter.parentId ? byId.get(filter.parentId) : undefined;
  // Filters the chips can't show (set by links): named here, each with its own ×.
  const extraFilters: { key: string; label: string }[] = [];
  if (filter.parentId) extraFilters.push({ key: "parentId", label: `Auf ${parentSystem?.name ?? "diesem Host"}` });
  if (filter.status && filter.status !== "offline") {
    extraFilters.push({ key: "status", label: `Zustand: ${STATUS_LABEL[filter.status] ?? filter.status}` });
  }
  if (filter.importance && filter.importance !== "critical") {
    extraFilters.push({ key: "importance", label: `Bedeutung: ${IMPORTANCE_LABEL[filter.importance] ?? filter.importance}` });
  }

  function renderRow(s: System) {
    const kindLabel = kindLabels[s.kind] ?? s.kind;
    const poe = (s.tags ?? []).some((t) => t.toLowerCase().includes("poe"));
    return (
      <li key={s.id} className={`inv-row${selected.has(s.id) ? " is-selected" : ""}`}>
        {selecting && (
          <label className="inv-check">
            <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggleSelected(s.id)}
                   aria-label={`${s.name} auswählen`} />
          </label>
        )}
        <Link to={`/geraete/${s.id}`} className="inv-link">
          <span className="inv-main">
            <span className="inv-name">
              <span className="inv-name-text">{s.name}</span>
              {s.importance === "critical" && <span className="inv-star" title="wichtig (kritisch)" aria-label="wichtig">★</span>}
              {!!s.errorCount && (
                <span className="inv-flag bad" title={`${s.errorCount} protokollierte(r) Fehler – siehe Geräteseite`}>
                  ⚠ {s.errorCount}
                </span>
              )}
              {poe && <span className="inv-flag warn" title="Funktioniert ohne PoE-fähigen Switch oder Injector nicht">PoE</span>}
            </span>
            {s.purpose && <span className="inv-sub inv-purpose">{s.purpose}</span>}
            <span className="inv-sub inv-phone-sub">{[s.ip || s.hostname, kindLabel].filter(Boolean).join(" · ")}</span>
          </span>
          <span className="inv-col inv-ip">
            <span className="mono">{s.ip || "—"}</span>
            {s.hostname && <span className="inv-sub">{s.hostname.split(".")[0]}</span>}
          </span>
          <span className="inv-col">{kindLabel}</span>
          <span className="inv-col">{s.location || "—"}</span>
          <StatusChip status={s.status} />
        </Link>
      </li>
    );
  }

  return (
    <div className={`geraete-calm${selecting ? " is-selecting" : ""}`}>
      {error && <div className="notice error" role="alert">{error}</div>}
      {notice && <p className="geraete-quiet" role="status">{notice}</p>}

      <div className="inv-toolbar">
        <input type="search" className="inv-search" placeholder="Name, IP, Hersteller, Raum …"
               aria-label="Geräte durchsuchen" value={filter.q}
               onChange={(e) => update({ q: e.target.value })} />
        <label className="inv-sort">
          <span className="visually-hidden">Sortieren</span>
          <select value={SORT_OPTIONS.some(([v]) => v === sortParam) ? sortParam : ""}
                  onChange={(e) => update({ sort: e.target.value })} aria-label="Sortieren">
            {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>Sortiert: {label}</option>)}
          </select>
        </label>
        {isAdmin && <button type="button" className="geraete-btn" onClick={() => setAdding(true)}>+ Gerät</button>}
      </div>

      <div className="inv-chips" role="group" aria-label="Filter">
        <button type="button" className={`sbtn geraete-filter${!anyFilter ? " active" : ""}`}
                aria-pressed={!anyFilter} onClick={() => update({ kind: "", project: "", parentId: "", status: "", importance: "" })}>
          Alle <b>{counts.total}</b>
        </button>
        <button type="button" className={`sbtn geraete-filter${filter.status === "offline" ? " active" : ""}`}
                aria-pressed={filter.status === "offline"}
                title="Alle Geräte, die beim letzten Scan bzw. der letzten Prüfung nicht geantwortet haben"
                onClick={() => update({ status: filter.status === "offline" ? "" : "offline" })}>
          <span className="dot bad" aria-hidden="true" />Nicht erreichbar <b>{counts.offline}</b>
        </button>
        <button type="button" className={`sbtn geraete-filter${filter.importance === "critical" ? " active" : ""}`}
                aria-pressed={filter.importance === "critical"}
                onClick={() => update({ importance: filter.importance === "critical" ? "" : "critical" })}>
          <span className="dot warn" aria-hidden="true" />Wichtig <b>{counts.critical}</b>
        </button>
        <label className={`geraete-filter geraete-filter-select${filter.kind ? " active" : ""}`}>
          <span className="visually-hidden">Art</span>
          <select value={filter.kind} onChange={(e) => update({ kind: e.target.value })} aria-label="Nach Art filtern">
            <option value="">Art ▾</option>
            {kindCounts.map(([k, n]) => <option key={k} value={k}>{kindLabels[k] ?? k} ({n})</option>)}
            {filter.kind && !kindCounts.some(([k]) => k === filter.kind) && (
              <option value={filter.kind}>{kindLabels[filter.kind] ?? filter.kind} (0)</option>
            )}
          </select>
        </label>
        {(projects.length > 0 || filter.project) && (
          <label className={`geraete-filter geraete-filter-select${filter.project ? " active" : ""}`}>
            <span className="visually-hidden">Compose-Projekt</span>
            <select value={filter.project} onChange={(e) => update({ project: e.target.value })} aria-label="Nach Compose-Projekt filtern">
              <option value="">Compose ▾</option>
              {projects.map((p) => <option key={p} value={p}>{p}</option>)}
              {filter.project && !projects.includes(filter.project) && <option value={filter.project}>{filter.project}</option>}
            </select>
          </label>
        )}
        {extraFilters.map((f) => (
          <button key={f.key} type="button" className="sbtn geraete-filter active" onClick={() => update({ [f.key]: "" })}
                  aria-label={`Filter „${f.label}“ entfernen`}>
            {f.label} <span aria-hidden="true">×</span>
          </button>
        ))}
        <span className="inv-chips-spacer" />
        {isAdmin && candidates.length > 0 && (
          <button type="button" className={`sbtn geraete-filter warn${reviewOpen ? " active" : ""}`}
                  aria-expanded={reviewOpen} aria-controls="inv-dupes"
                  onClick={() => update({ duplikate: reviewOpen ? "" : "1" }, true)}>
            <span className="dot warn" aria-hidden="true" />{plural(candidates.length, "mögliches Duplikat", "mögliche Duplikate")}
          </button>
        )}
        {isAdmin && all.length > 0 && !selecting && (
          <button type="button" className="sbtn geraete-filter" onClick={() => setSelecting(true)}>Auswählen</button>
        )}
      </div>

      {reviewOpen && (
        <section id="inv-dupes" className="inv-panel" aria-labelledby="inv-dupes-title">
          <div className="inv-panel-head">
            <h2 id="inv-dupes-title">Mögliche Duplikate</h2>
            <button type="button" className="secondary geraete-btn" onClick={() => update({ duplikate: "" }, true)}>Schließen</button>
          </div>
          <p className="geraete-quiet">
            Zwei Einträge, die vermutlich dasselbe Gerät sind. Zusammengeführt wird erst nach deiner Bestätigung.
          </p>
          {candidates.length === 0 ? (
            <p className="geraete-quiet">Keine Verdachtsfälle mehr.</p>
          ) : (
            <ul className="inv-dupe-list">
              {candidates.map((c) => (
                <li key={`${c.aId}-${c.bId}`}>
                  <div className="inv-dupe-text">
                    <b>„{c.aName}“</b> und <b>„{c.bName}“</b>
                    <span className="inv-sub">{c.reasons.map((r) => DUPLICATE_REASON_LABEL[r]).join(", ")}</span>
                  </div>
                  <div className="inv-dupe-actions">
                    <button type="button" className="secondary geraete-btn" disabled={busy}
                            onClick={() => askMerge(c.aId, c.bId, c.aName, c.bName)}>Behalte „{c.aName}“</button>
                    <button type="button" className="secondary geraete-btn" disabled={busy}
                            onClick={() => askMerge(c.bId, c.aId, c.bName, c.aName)}>Behalte „{c.bName}“</button>
                    <button type="button" className="secondary geraete-btn" disabled={busy}
                            onClick={() => void notDuplicate(c)}>Kein Duplikat</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {selecting && (
        <div className="inv-selectbar" role="region" aria-label="Auswahl">
          <span className="inv-selectbar-count"><b>{selected.size}</b> ausgewählt</span>
          <button type="button" className="secondary geraete-btn"
                  onClick={() => setSelected(allVisibleSelected ? new Set() : new Set(visible.map((s) => s.id)))}>
            {allVisibleSelected ? "Keine" : "Alle sichtbaren"}
          </button>
          {selectedList.length === 2 && (
            <span className="inv-merge">
              <span className="geraete-quiet">Zusammenführen, behalte</span>
              {selectedList.map((s) => {
                const other = selectedList.find((o) => o.id !== s.id)!;
                return (
                  <button key={s.id} type="button" className="secondary geraete-btn" disabled={busy}
                          onClick={() => askMerge(s.id, other.id, s.name, other.name)}>„{s.name}“</button>
                );
              })}
            </span>
          )}
          <span className="inv-chips-spacer" />
          <button type="button" className="geraete-btn danger" disabled={busy || selected.size === 0}
                  onClick={() => setPending({ kind: "delete", ids: [...selected] })}>
            Löschen …
          </button>
          <button type="button" className="secondary geraete-btn" onClick={stopSelecting}>Fertig</button>
        </div>
      )}

      {(anyFilter || filter.q) && visible.length > 0 && (
        <p className="geraete-quiet inv-result">
          {plural(visible.length, "Treffer", "Treffer")}
          <button type="button" className="sbtn geraete-link" onClick={clearFilters}>Filter zurücksetzen</button>
        </p>
      )}

      {all.length === 0 ? (
        <div className="geraete-empty">
          <h2>Noch keine Geräte erfasst</h2>
          <p>Ein Netzwerk-Scan findet die Geräte im Haus automatisch; einzelne Geräte lassen sich auch von Hand eintragen.</p>
          {isAdmin && (
            <div className="geraete-actions">
              <Link className="geraete-btn primary" to="/scan">Netzwerk scannen</Link>
              <button type="button" className="secondary geraete-btn" onClick={() => setAdding(true)}>+ Gerät von Hand</button>
            </div>
          )}
        </div>
      ) : visible.length === 0 ? (
        <div className="geraete-empty">
          <p>Kein Gerät passt zu {filter.q ? `„${filter.q}“` : "diesem Filter"}.</p>
          <div className="geraete-actions">
            <button type="button" className="secondary geraete-btn" onClick={clearFilters}>Filter zurücksetzen</button>
          </div>
        </div>
      ) : (
        <ul className="inv-list" aria-label="Geräte">
          <li className="inv-head" aria-hidden="true">
            {selecting && <span className="inv-check" />}
            <span className="inv-head-cols">
              <span>Gerät</span><span>Adresse</span><span>Art</span><span>Standort</span><span>Zustand</span>
            </span>
          </li>
          {groups.loose.map(renderRow)}
          {groups.stacks.map((g) => {
            const open = !collapsed.has(g.name);
            return (
              <li key={`stack:${g.name}`} className="inv-group">
                <button type="button" className="sbtn inv-group-head" aria-expanded={open} onClick={() => toggleCollapsed(g.name)}>
                  <span aria-hidden="true">{open ? "▾" : "▸"}</span> Compose: <b>{g.name}</b>
                  <span className="geraete-quiet">· {plural(g.items.length, "Container", "Container")}</span>
                </button>
                {open && <ul className="inv-list inv-group-list">{g.items.map(renderRow)}</ul>}
              </li>
            );
          })}
        </ul>
      )}

      <AddDeviceDialog open={adding} kindLabels={kindLabels} onCancel={() => setAdding(false)}
                       onCreated={(system) => { setAdding(false); navigate(`/geraete/${system.id}`); }} />
      {dialog}
    </div>
  );
}
