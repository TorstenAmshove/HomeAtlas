import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api, DUPLICATE_REASON_LABEL, type Account, type ConfigVersion, type DeviceErrorEvent, type DuplicateCandidate,
  type MonitorState, type ProbeResult, type System, type SystemAlias,
} from "../../lib/api";
import { useAuth } from "../../App";
import ConfirmDialog from "../../components/ConfirmDialog";
import DeviceEditForm from "../../components/DeviceEditForm";
import OverflowMenu, { type OverflowItem } from "../../components/OverflowMenu";
import { Skeleton, SkeletonText } from "../../components/Skeleton";
import { hasConfigHistory } from "../../lib/device";
import { clearDeviceDraft, formOf, readDeviceDraft, sameForm, storeDeviceDraft } from "../../lib/deviceDraft";
import { useLeaveGuard } from "../../lib/useLeaveGuard";
import { useUndoToast } from "../../lib/useUndoToast";
import { useUrlState } from "../../lib/useUrlState";
import { usePageTitle } from "../../shell/pageTitle";
import { NoticeLine, StateChip, fullDate, when, type Notice } from "./common";
import UeberblickTab, { recentHistory } from "./UeberblickTab";
import TechnikTab from "./TechnikTab";
import VerlaufTab from "./VerlaufTab";
import ZugaengeTab from "./ZugaengeTab";
import SteuernTab from "./SteuernTab";
import "./device.css";

/**
 * Device page of the redesigned UI (docs/redesign/5-information-architecture.md, "Gerät"), shown
 * for `/geraete/:id` while `useUi().calm` is on; otherwise SystemDetailPage renders unchanged.
 *
 * Summary first, on the overview tab only: one strip (status · since · address · source ·
 * importance), then exactly one primary next action that depends on the state, quiet secondary
 * buttons and "⋯" for the rest. The 15 stacked sections of the classic page are split into tabs
 * kept in `?tab=` (Überblick · Technik · Verlauf · Zugänge · Steuern); nothing was dropped, see the
 * route-map table in the PR. Every call is one the classic page already makes.
 *
 * Status follows the Start page's rule: a live chip only when the monitor is on and watches this
 * device (`/api/monitor`), otherwise "Stand letzter Scan".
 */

type TabId = "ueberblick" | "technik" | "verlauf" | "zugaenge" | "steuern";

const IMPORTANCE_WORD: Record<System["importance"], string> = { critical: "kritisch", normal: "normal", low: "gering" };
const SCAN_WORD: Record<string, string> = { online: "erreichbar", offline: "nicht erreichbar" };

interface Loaded {
  system: System;
  accounts: Account[];
  derived: string;
  monitorPorts: number[];
}

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

function DeviceSkeleton() {
  return (
    <div className="device-calm" role="status" aria-live="polite">
      <span className="visually-hidden">Wird geladen …</span>
      <div className="dv-strip">
        {[90, 120, 110, 100, 130].map((w, i) => (
          <div key={i} className="dv-strip-item"><Skeleton width={56} height={10} /><Skeleton width={w} /></div>
        ))}
      </div>
      <div className="dv-actions"><Skeleton width={150} height={44} radius={8} /><Skeleton width={110} height={44} radius={8} /></div>
      <div className="dv-tabs"><Skeleton width="min(420px, 90%)" height={18} /></div>
      <div className="dv-overview">
        <div><Skeleton width={80} height={12} style={{ margin: "18px 0 10px" }} /><SkeletonText lines={4} /></div>
        <div><Skeleton width={80} height={12} style={{ margin: "18px 0 10px" }} /><SkeletonText lines={3} /></div>
      </div>
    </div>
  );
}

export default function DeviceCalm() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [tabParam, setTab] = useUrlState("tab", "ueberblick");
  const [editParam, setEditParam] = useUrlState("edit");
  const [toast, showToast] = useUndoToast();

  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [monitor, setMonitor] = useState<MonitorState | null>(null);
  const [errorEvents, setErrorEvents] = useState<DeviceErrorEvent[] | null>(null);
  const [configVersions, setConfigVersions] = useState<ConfigVersion[] | null>(null);
  const [aliases, setAliases] = useState<SystemAlias[] | null>(null);
  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([]);

  const [probing, setProbing] = useState(false);
  const [probeNotice, setProbeNotice] = useState<Notice>(null);
  const [checking, setChecking] = useState(false);
  const [checkNotice, setCheckNotice] = useState<Notice>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [merge, setMerge] = useState<{ choice: string; others: System[] | null; error: string } | null>(null);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);

  const [draft, setDraft] = useState<Partial<System> | null>(null);
  const [saving, setSaving] = useState(false);
  // Bumped after discarding a stored draft, so the page re-renders and re-reads sessionStorage.
  const [, setDraftVersion] = useState(0);
  const pushedEdit = useRef(false);

  const system = data?.system ?? null;
  const editing = isAdmin && editParam === "1";
  usePageTitle(system?.name ?? null);

  const loadSystem = useCallback(async () => {
    const r = await api.getSystem(id);
    setData({ system: r.system, accounts: r.accounts, derived: r.description, monitorPorts: r.monitorPortsEffective });
    return r.system;
  }, [id]);

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const loaded = await loadSystem();
      api.monitor().then(setMonitor).catch(() => setMonitor(null));
      // Fetched for every device: any device can collect a probe failure or a monitoring event.
      api.listSystemErrors(id).then((r) => setErrorEvents(r.events)).catch(() => setErrorEvents([]));
      if (isAdmin) {
        // Config backups only exist for routers/switches; admin-only (an export can carry secrets).
        if (hasConfigHistory(loaded)) {
          api.listConfigVersions(id).then((r) => setConfigVersions(r.versions)).catch(() => setConfigVersions([]));
        }
        api.getSystemAliases(id).then((r) => setAliases(r.aliases)).catch(() => setAliases([]));
        api.getDuplicateCandidates()
          .then((r) => setCandidates(r.candidates.filter((c) => c.aId === id || c.bId === id)))
          .catch(() => setCandidates([]));
      }
    } catch (e) {
      setError(errorText(e));
    }
  }, [id, isAdmin, loadSystem]);

  useEffect(() => {
    setData(null);
    setMonitor(null);
    setErrorEvents(null);
    setConfigVersions(null);
    setAliases(null);
    setCandidates([]);
    setProbeNotice(null);
    setCheckNotice(null);
    setNotice(null);
    void loadAll();
  }, [loadAll]);

  // Live status: re-read /api/monitor at the monitor's own pace (never under 5 s), only while the
  // tab is visible -- the same rule as the Start page.
  useEffect(() => {
    if (!monitor?.enabled) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") api.monitor().then(setMonitor).catch(() => {});
    }, Math.max(5, monitor.intervalSeconds) * 1000);
    return () => window.clearInterval(timer);
  }, [monitor?.enabled, monitor?.intervalSeconds]);

  // Edit mode (?edit=1): the form starts from the stored draft if there is one.
  useEffect(() => {
    if (!system) return;
    if (editing) setDraft((current) => current ?? { ...system, ...(readDeviceDraft(id) ?? {}) });
    else setDraft(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, system === null, id]);

  const dirty = editing && system !== null && draft !== null && !sameForm(draft, system);
  const [leaveDialog] = useLeaveGuard(dirty, system ? `„${system.name}“` : "diesem Gerät");
  const storedDraft = isAdmin && !editing && system ? readDeviceDraft(id) : null;
  const hasStoredDraft = storedDraft !== null && system !== null && !sameForm({ ...system, ...storedDraft }, system);

  function openEdit() {
    pushedEdit.current = true;
    setEditParam("1", { push: true });
  }

  function closeEdit() {
    if (pushedEdit.current) {
      pushedEdit.current = false;
      navigate(-1);
    } else {
      setEditParam("");
    }
  }

  function updateDraft(next: Partial<System>) {
    setDraft(next);
    if (system) storeDeviceDraft(id, next, system);
  }

  async function save() {
    if (!system || !draft) return;
    setSaving(true);
    try {
      // Same request as the classic page: the device with the form's fields laid over it.
      const { system: updated } = await api.updateSystem(id, { ...system, ...formOf(draft) });
      clearDeviceDraft(id);
      setData((current) => (current ? { ...current, system: updated } : current));
      setDraft(null);
      closeEdit();
      showToast({ message: "Gespeichert. Diese Angaben bleiben bei künftigen Scans erhalten." });
      void loadSystem().catch(() => {});
    } catch (e) {
      setNotice({ kind: "error", text: errorText(e) });
    } finally {
      setSaving(false);
    }
  }

  function cancelEdit() {
    clearDeviceDraft(id);
    setDraft(null);
    closeEdit();
  }

  async function probe() {
    setProbing(true);
    setProbeNotice(null);
    try {
      const { outcome, system: updated } = await api.probeSystem(id);
      setData((current) => (current ? { ...current, system: updated } : current));
      if (isAdmin && hasConfigHistory(updated)) {
        void api.listConfigVersions(id).then((cv) => setConfigVersions(cv.versions));
      }
      if (outcome.ran) {
        setProbeNotice({ kind: "ok", text: `Gerät ausgelesen über: ${Object.keys(outcome.results).join(", ")}` });
      } else {
        const reasons = Object.values(outcome.results).map((r) => r.error).filter(Boolean);
        setProbeNotice({ kind: "error", text: reasons.length > 0 ? reasons.join(" · ") : outcome.reason || "Keine Verbindung möglich." });
      }
    } catch (e) {
      setProbeNotice({ kind: "error", text: errorText(e) });
    } finally {
      setProbing(false);
    }
  }

  async function checkNow() {
    setChecking(true);
    setCheckNotice(null);
    try {
      await api.monitorRunNow();
      const [state] = await Promise.all([api.monitor(), loadSystem()]);
      setMonitor(state);
      const now = new Date().toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
      const after = state.systems.find((s) => s.id === id)?.status;
      setCheckNotice(after === "online"
        ? { kind: "ok", text: `Geprüft ${now}: wieder erreichbar.` }
        : { kind: "info", text: `Geprüft ${now}: weiterhin nicht erreichbar.` });
    } catch (e) {
      setCheckNotice({ kind: "error", text: errorText(e) });
    } finally {
      setChecking(false);
    }
  }

  function candidateName(otherId: string): string | undefined {
    return candidates.map((c) => (c.aId === otherId ? c.aName : c.bId === otherId ? c.bName : "")).find(Boolean);
  }

  async function openMerge(preset = "") {
    setMerge({ choice: preset, others: null, error: "" });
    try {
      const r = await api.listSystems();
      setMerge((m) => m && {
        ...m, others: r.systems.filter((s) => s.id !== id).sort((a, b) => a.name.localeCompare(b.name, "de")),
      });
    } catch (e) {
      setMerge((m) => m && { ...m, others: [], error: errorText(e) });
    }
  }

  async function runMerge() {
    if (!merge || !system) return;
    if (!merge.choice) {
      setMerge({ ...merge, error: "Bitte zuerst das doppelte Gerät wählen." });
      return;
    }
    const removed = merge.others?.find((s) => s.id === merge.choice)?.name
      ?? candidateName(merge.choice) ?? "das andere Gerät";
    setMergeBusy(true);
    try {
      await api.mergeSystems(id, merge.choice);
      setMerge(null);
      // The kept device is this one: land on its overview (tab/edit dropped) and reload in place,
      // instead of the classic page's window.location.reload() (forensics "Gerät" 7).
      navigate(`/geraete/${id}`, { replace: true });
      await loadAll();
      showToast({ message: `Zusammengeführt: „${removed}“ ist jetzt Teil von „${system.name}“.` });
    } catch (e) {
      setMerge((m) => m && { ...m, error: errorText(e) });
    } finally {
      setMergeBusy(false);
    }
  }

  async function notDuplicate(otherId: string) {
    try {
      await api.markNotDuplicate(id, otherId);
      setCandidates((current) => current.filter((c) => c.aId !== otherId && c.bId !== otherId));
    } catch (e) {
      setNotice({ kind: "error", text: errorText(e) });
    }
  }

  async function runDelete() {
    setDeleteBusy(true);
    try {
      await api.deleteSystem(id);
      clearDeviceDraft(id);
      setDeleteOpen(false);
      navigate("/geraete", { replace: true });
    } catch (e) {
      setNotice({ kind: "error", text: errorText(e) });
      setDeleteOpen(false);
    } finally {
      setDeleteBusy(false);
    }
  }

  if (error && !data) {
    return (
      <div className="device-calm">
        <div className="notice error">{error}</div>
        <Link className="dv-link" to="/geraete">Zur Geräteliste</Link>
      </div>
    );
  }
  if (!data || !system) return <DeviceSkeleton />;

  const { accounts, derived, monitorPorts } = data;

  // ---------------------------------------------------------------- status (Start page rule)
  const watched = monitor?.systems.find((s) => s.id === id);
  const live = Boolean(monitor?.enabled && watched);
  const status = (live ? watched!.status : system.status) as System["status"];
  const monitorEvents = (monitor?.events ?? []).filter((e) => e.systemId === id);
  const lastChange = monitorEvents[0];
  const offline = status === "offline";

  const probeSources = Object.keys((system.extra?.probe ?? {}) as Record<string, ProbeResult>);
  const interfaceIps = Object.keys((system.extra?.interfaces ?? {}) as Record<string, unknown>).filter((ip) => ip !== system.ip);
  const aliasIps = (aliases ?? []).map((a) => a.ip).filter((ip) => ip && ip !== system.ip);
  const otherIps = Array.from(new Set([...interfaceIps, ...aliasIps]));
  const canProbe = isAdmin && accounts.some((a) => a.allowProbe);
  const directAccounts = accounts.filter((a) => !a.viaAssignment);
  const assignedAccounts = accounts.filter((a) => a.viaAssignment);

  const tabs: { id: TabId; label: string }[] = [
    { id: "ueberblick", label: "Überblick" },
    { id: "technik", label: "Technik" },
    { id: "verlauf", label: "Verlauf" },
    ...(isAdmin ? [{ id: "zugaenge" as const, label: "Zugänge" }, { id: "steuern" as const, label: "Steuern" }] : []),
  ];
  const tab: TabId = tabs.some((t) => t.id === tabParam) ? (tabParam as TabId) : "ueberblick";
  const history = errorEvents === null ? null : recentHistory(monitorEvents, errorEvents);

  // ---------------------------------------------------------------- strip
  let statusChip;
  if (!live) {
    statusChip = (
      <>
        <StateChip tone="" title="Wird nicht laufend geprüft – Zustand vom letzten Scan">Stand letzter Scan</StateChip>
        <small>beim Scan {SCAN_WORD[system.status] ?? "unbekannt"}</small>
      </>
    );
  } else if (status === "online") {
    statusChip = <StateChip tone="ok">erreichbar</StateChip>;
  } else if (status === "offline") {
    statusChip = <StateChip tone="bad">nicht erreichbar</StateChip>;
  } else {
    statusChip = <StateChip tone="">wird geprüft …</StateChip>;
  }
  const sinceItem = live && lastChange
    ? { label: "Seit", value: when(lastChange.at), title: fullDate(lastChange.at) }
    : system.lastSeen
      ? { label: "Zuletzt gesehen", value: when(system.lastSeen), title: fullDate(system.lastSeen) }
      : null;
  const source = [
    system.discoverySource || (system.discovered ? "Scan" : "von Hand angelegt"),
    probeSources.length > 0 ? `ausgelesen über ${probeSources.join(", ")}` : "",
  ].filter(Boolean).join(" · ");
  const watching = system.monitored === 1
    ? `überwacht per ${monitorPorts.length > 0 ? `Port ${monitorPorts.join(", ")}` : "Ping"}`
    : "nicht überwacht";

  // ---------------------------------------------------------------- actions
  const webLink = system.url ? (
    <a className={`dv-btn${offline ? "" : " primary"}`} href={system.url} target="_blank" rel="noreferrer">
      Weboberfläche ↗
    </a>
  ) : null;
  let primary = null;
  if (offline && live && isAdmin) {
    primary = (
      <>
        <button type="button" className="dv-btn primary" onClick={() => void checkNow()} disabled={checking}>
          {checking ? "Prüfe …" : "Jetzt neu prüfen"}
        </button>
        <Link className="dv-btn" to="/assistent">Assistent fragen</Link>
        {webLink}
      </>
    );
  } else if (offline) {
    primary = (
      <>
        <Link className="dv-btn primary" to="/assistent">Assistent fragen</Link>
        {webLink}
      </>
    );
  } else {
    primary = webLink;
  }
  const openExternal = (url: string) => window.open(url, "_blank", "noopener,noreferrer");
  const moreItems: OverflowItem[] = [
    ...(canProbe ? [{ label: probing ? "Gerät wird ausgelesen …" : "Gerät auslesen", onSelect: () => { setTab("technik", { push: true }); void probe(); }, disabled: probing }] : []),
    ...(system.docUrl ? [{ label: "Hersteller-Doku ↗", onSelect: () => openExternal(system.docUrl) }] : []),
    ...(system.docLink ? [{ label: "Eigene Doku ↗", onSelect: () => openExternal(system.docLink) }] : []),
    ...(isAdmin ? [
      { label: "Zusammenführen …", onSelect: () => void openMerge() },
      { label: "Löschen …", onSelect: () => setDeleteOpen(true), danger: true },
    ] : []),
  ];

  const mergeTarget = merge?.choice ? merge.others?.find((s) => s.id === merge.choice) : undefined;
  const mergeTargetName = mergeTarget?.name ?? (merge?.choice ? candidateName(merge.choice) : "") ?? "";

  return (
    <div className="device-calm">
      {leaveDialog}
      {toast}
      <h1 className="visually-hidden">{system.name}</h1>

      <ConfirmDialog
        open={deleteOpen}
        title={`„${system.name}“ löschen?`}
        danger
        busy={deleteBusy}
        confirmLabel="Gerät endgültig löschen"
        consequences={[
          <>Das Gerät „{system.name}“ wird mit allen Angaben, Notizen und dem Verlauf aus HomeAtlas entfernt.</>,
          directAccounts.length === 0
            ? <>Diesem Gerät sind keine Zugänge direkt zugeordnet; es wird kein Zugang gelöscht.</>
            : <>
                {directAccounts.length === 1 ? "Dieser Zugang wird mitgelöscht" : `Diese ${directAccounts.length} Zugänge werden mitgelöscht`}
                {" "}(samt gespeicherten Passwörtern):
                <ul className="dv-dialog-list" data-testid="delete-accounts">
                  {directAccounts.map((a) => <li key={a.id}>{a.label}{a.username ? ` (${a.username})` : ""}</li>)}
                </ul>
              </>,
          ...(assignedAccounts.length > 0
            ? [<>{assignedAccounts.length === 1 ? "1 Zugang ist" : `${assignedAccounts.length} Zugänge sind`} nur über eine Regel zugeordnet und bleiben erhalten.</>]
            : []),
        ]}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={runDelete}
      >
        <p className="dv-dialog-note">
          Das lässt sich nicht rückgängig machen; es gibt keinen Papierkorb und kein Archiv für Geräte.
          Findet ein späterer Scan das Gerät wieder, erscheint es neu, aber ohne deine Angaben und
          ohne die gelöschten Zugänge. Wenn es nur doppelt ist: „Zusammenführen“ behält alles.
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={merge !== null}
        title={`Mit „${system.name}“ zusammenführen`}
        busy={mergeBusy}
        confirmLabel="Zusammenführen"
        consequences={mergeTargetName ? [
          <>„{mergeTargetName}“ wird gelöscht; „{system.name}“ bleibt.</>,
          <>Zugänge und Verlauf von „{mergeTargetName}“ gehen auf „{system.name}“ über.</>,
          <>Leere Felder, offene Ports, Dienste und Geräteinfos von dort werden hier ergänzt; bei Widersprüchen gilt „{system.name}“.</>,
          <>Spätere Scans ordnen Adresse und MAC von „{mergeTargetName}“ diesem Gerät zu.</>,
        ] : undefined}
        onCancel={() => setMerge(null)}
        onConfirm={runMerge}
      >
        <div className="field">
          <label htmlFor="dv-merge-choice">Welches Gerät ist dasselbe wie „{system.name}“?</label>
          {merge?.others === null ? (
            <Skeleton width="100%" height={40} />
          ) : (
            <select id="dv-merge-choice" value={merge?.choice ?? ""}
                    onChange={(e) => setMerge((m) => m && { ...m, choice: e.target.value, error: "" })}>
              <option value="">Gerät wählen …</option>
              {(merge?.others ?? []).map((s) => (
                <option key={s.id} value={s.id}>{s.name}{s.ip ? ` (${s.ip})` : ""}</option>
              ))}
            </select>
          )}
        </div>
        {merge?.error && <div className="notice error" role="alert">{merge.error}</div>}
        <p className="dv-dialog-note">Das lässt sich nicht rückgängig machen.</p>
      </ConfirmDialog>

      <ConfirmDialog
        open={discardOpen}
        title="Entwurf verwerfen?"
        consequences={[<>Deine ungespeicherten Änderungen an „{system.name}“ gehen verloren.</>]}
        confirmLabel="Verwerfen"
        danger
        onCancel={() => setDiscardOpen(false)}
        onConfirm={() => { clearDeviceDraft(id); setDiscardOpen(false); setDraftVersion((v) => v + 1); }}
      />

      <NoticeLine notice={notice} />

      {editing ? (
        <section className="dv-edit" aria-labelledby="dv-edit-title">
          <h2 className="dv-sec" id="dv-edit-title">Bearbeiten</h2>
          {draft && (
            <DeviceEditForm title={null} draft={draft} onChange={updateDraft} saving={saving}
                            onSave={() => void save()} onCancel={cancelEdit} />
          )}
        </section>
      ) : (
        <>
          {hasStoredDraft && (
            <div className="dv-draft" role="status">
              <span>Ungespeicherte Änderungen an diesem Gerät.</span>
              <span className="dv-control-buttons">
                <button type="button" className="secondary dv-btn-small" onClick={openEdit}>Weiter bearbeiten</button>
                <button type="button" className="secondary dv-btn-small" onClick={() => setDiscardOpen(true)}>Verwerfen …</button>
              </span>
            </div>
          )}

          {tab === "ueberblick" && (
            <>
              <section className="dv-strip" aria-label="Zusammenfassung">
                <div className="dv-strip-item"><small>Status</small><span className="dv-strip-status">{statusChip}</span></div>
                {sinceItem && (
                  <div className="dv-strip-item" title={sinceItem.title}><small>{sinceItem.label}</small><b>{sinceItem.value}</b></div>
                )}
                <div className="dv-strip-item">
                  <small>Adresse</small>
                  <b className="mono">{system.ip || system.hostname || "keine"}</b>
                  {otherIps.length > 0 && <small title={otherIps.join(", ")}>+{otherIps.length} weitere</small>}
                </div>
                <div className="dv-strip-item"><small>Quelle</small><b>{source}</b></div>
                <div className="dv-strip-item">
                  <small>Wichtig</small>
                  <b>{IMPORTANCE_WORD[system.importance] ?? system.importance} · {watching}</b>
                </div>
              </section>

              <div className="dv-actions">
                {primary}
                {isAdmin && <button type="button" className="secondary dv-btn" onClick={openEdit}>Bearbeiten</button>}
                {moreItems.length > 0 && <OverflowMenu items={moreItems} label="Weitere Aktionen" />}
              </div>
              <NoticeLine notice={checkNotice} />

              {isAdmin && candidates.map((c) => {
                const otherId = c.aId === id ? c.bId : c.aId;
                const otherName = c.aId === id ? c.bName : c.aName;
                return (
                  <div key={otherId} className="dv-dup" role="status">
                    <span className="dv-chip warn"><span className="dot" aria-hidden="true" />Mögliches Duplikat</span>
                    <span>„{otherName}“ ({c.reasons.map((r) => DUPLICATE_REASON_LABEL[r]).join(", ")})</span>
                    <span className="dv-control-buttons">
                      <button type="button" className="secondary dv-btn-small" onClick={() => void openMerge(otherId)}>Zusammenführen …</button>
                      <button type="button" className="secondary dv-btn-small" onClick={() => void notDuplicate(otherId)}>Kein Duplikat</button>
                    </span>
                  </div>
                );
              })}
            </>
          )}

          <nav className={`dv-tabs${tab === "ueberblick" ? "" : " dv-tabs-top"}`} aria-label="Bereiche dieses Geräts">
            {tabs.map((t) => (
              <Link key={t.id} to={{ search: t.id === "ueberblick" ? "" : `?tab=${t.id}` }}
                    className={`dv-tab${tab === t.id ? " active" : ""}`} aria-current={tab === t.id ? "page" : undefined}>
                {t.label}
              </Link>
            ))}
          </nav>

          {tab === "ueberblick" && (
            <UeberblickTab system={system} derived={derived} accounts={accounts} isAdmin={isAdmin} history={history} />
          )}
          {tab === "technik" && (
            <TechnikTab system={system} monitorPorts={monitorPorts} aliases={aliases} isAdmin={isAdmin}
                        canProbe={canProbe} probing={probing} probeNotice={probeNotice} onProbe={() => void probe()} />
          )}
          {tab === "verlauf" && (
            <VerlaufTab systemId={id} errorEvents={errorEvents} monitorEvents={monitorEvents}
                        monitorEnabled={Boolean(monitor?.enabled)} configVersions={configVersions}
                        showConfig={isAdmin && hasConfigHistory(system)} />
          )}
          {tab === "zugaenge" && isAdmin && (
            <ZugaengeTab systemId={id} systemName={system.name} accounts={accounts}
                         onAccountsChanged={async () => { await loadSystem(); }} />
          )}
          {tab === "steuern" && isAdmin && (
            <SteuernTab system={system} status={status} accounts={accounts}
                        onSystemChanged={async () => { await loadSystem(); }} />
          )}
        </>
      )}
    </div>
  );
}
