import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type DocPage, type DocVersion } from "../lib/api";
import { useAuth } from "../App";
import Markdown from "../components/Markdown";
import ConfirmDialog from "../components/ConfirmDialog";
import OverflowMenu from "../components/OverflowMenu";
import { Skeleton, SkeletonText } from "../components/Skeleton";
import { draftKeys, readDraft, writeDraft } from "../lib/drafts";
import { useLeaveGuard } from "../lib/useLeaveGuard";
import { useUndoToast } from "../lib/useUndoToast";
import { useUrlState } from "../lib/useUrlState";

/**
 * Documentation chapters (Hilfe → Dokumentation).
 *
 * Unsaved text -- the "Bearbeiten" draft and the "Eigene Notizen" draft -- is kept per chapter in
 * sessionStorage (lib/drafts.ts) and restored when the chapter is opened again; leaving with unsaved
 * changes asks first (lib/useLeaveGuard.tsx): losing a draft by clicking another chapter was a bug,
 * not a design choice (forensics "Dokumentation" 1).
 */

const NOTFALL = "notfall";

type Pending =
  | { kind: "all" }
  | { kind: "reset" }
  | { kind: "restore"; version: DocVersion }
  | null;

/** "heute 03:04", "gestern 18:20" or "12.11.2026, 09:15". */
function formatStand(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const time = date.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return `heute ${time}`;
  if (date.toDateString() === yesterday.toDateString()) return `gestern ${time}`;
  return date.toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" });
}

export default function DocsPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [pages, setPages] = useState<Omit<DocPage, "bodyMd">[]>([]);
  const [pagesLoaded, setPagesLoaded] = useState(false);
  const [page, setPage] = useState<DocPage | null>(null);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [versions, setVersions] = useState<DocVersion[] | null>(null);
  const [preview, setPreview] = useState<DocVersion | null>(null);
  const [manualDraft, setManualDraft] = useState<string | null>(null);
  const [restoredDraft, setRestoredDraft] = useState(false);
  // History panel open state lives in `?versions=1`, so Back/reload keep it.
  const [versionsParam, setVersionsParam] = useUrlState("versions");
  const versionsOpen = versionsParam === "1";
  const [pending, setPending] = useState<Pending>(null);
  const [toast, showToast] = useUndoToast();
  const slugRef = useRef(slug);
  slugRef.current = slug;
  // Current value for the Undo callback, which runs up to 12 s later (the panel may have changed).
  const versionsOpenRef = useRef(versionsOpen);
  versionsOpenRef.current = versionsOpen;

  const dirty = Boolean(page) && (
    (editing && draft !== page!.bodyMd) ||
    (manualDraft !== null && manualDraft !== (page!.manualMd ?? ""))
  );
  const [leaveDialog, leave] = useLeaveGuard(dirty, page ? `„${page.title}“` : "diesem Kapitel");

  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }

  useEffect(() => {
    api.listDocs()
      .then((r) => setPages(r.pages))
      .catch((e) => setError(e.message))
      .finally(() => setPagesLoaded(true));
  }, []);

  useEffect(() => {
    setPreview(null);
    // An error belongs to the chapter it happened on; the next chapter starts without it.
    setError("");
    if (!slug) {
      setPage(null);
      setEditing(false);
      setManualDraft(null);
      setRestoredDraft(false);
      return;
    }
    // Restore what was typed into this chapter earlier in this tab instead of starting blank.
    const bodyDraft = readDraft(draftKeys.docBody(slug));
    const notesDraft = readDraft(draftKeys.docManual(slug));
    // Only admins can edit; a draft left in this tab by another (admin) login is not reopened for a
    // member, who would get an editor without a save button.
    const restoreBody = isAdmin && bodyDraft !== null;
    const restoreNotes = isAdmin && notesDraft !== null;
    setEditing(restoreBody);
    setDraft(restoreBody ? bodyDraft : "");
    setManualDraft(restoreNotes ? notesDraft : null);
    setRestoredDraft(restoreBody || restoreNotes);
    setPage(null);
    let cancelled = false;
    api.getDoc(slug)
      .then((r) => { if (!cancelled) setPage(r.page); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [slug]);

  useEffect(() => {
    if (!slug || !versionsOpen) {
      setVersions(null);
      setPreview(null);
      return;
    }
    let cancelled = false;
    api.listDocVersions(slug)
      .then((r) => { if (!cancelled) setVersions(r.versions); })
      .catch((e) => { if (!cancelled) fail(e); });
    return () => { cancelled = true; };
  }, [slug, versionsOpen]);

  function toggleVersions() {
    setVersionsParam(versionsOpen ? "" : "1", { push: true });
  }

  async function showVersion(version: DocVersion) {
    if (!slug) return;
    try {
      setPreview((await api.getDocVersion(slug, version.id)).version);
    } catch (e) {
      fail(e);
    }
  }

  async function doRestore(version: DocVersion) {
    if (!slug) return;
    setBusy(true);
    try {
      setPage((await api.restoreDocVersion(slug, version.id)).page);
      setVersions((await api.listDocVersions(slug)).versions);
      setPreview(null);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  function restoreVersion(version: DocVersion) {
    setPending({ kind: "restore", version });
  }

  async function regenerate() {
    setBusy(true);
    setError("");
    try {
      await api.generateDocs(true);
      const list = await api.listDocs();
      setPages(list.pages);
      if (slug) setPage((await api.getDoc(slug)).page);
      if (slug && versionsOpen) setVersions((await api.listDocVersions(slug)).versions);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // --- drafts: every change is written through to sessionStorage under the chapter's own key.

  // A restored body draft that started from an older version of this chapter (the chapter changed in
  // the meantime): saving would replace the newer text, so say so instead of silently overwriting.
  const draftBase = slug ? readDraft(draftKeys.docBase(slug)) : null;
  const draftIsStale = Boolean(restoredDraft && editing && page && draftBase !== null && draftBase !== (page.updatedAt ?? ""));

  function changeDraft(value: string) {
    setDraft(value);
    if (slug) {
      writeDraft(draftKeys.docBody(slug), value);
      // Remember which version of the chapter this draft started from (first keystroke only).
      if (readDraft(draftKeys.docBase(slug)) === null && page) writeDraft(draftKeys.docBase(slug), page.updatedAt ?? "");
    }
  }

  function closeEditor() {
    setEditing(false);
    setRestoredDraft(false);
    if (slug) {
      writeDraft(draftKeys.docBody(slug), null);
      writeDraft(draftKeys.docBase(slug), null);
    }
  }

  function changeManual(value: string) {
    setManualDraft(value);
    if (slug) writeDraft(draftKeys.docManual(slug), value);
  }

  function closeManual() {
    setManualDraft(null);
    setRestoredDraft(false);
    if (slug) writeDraft(draftKeys.docManual(slug), null);
  }

  async function save() {
    if (!slug) return;
    setBusy(true);
    try {
      setPage((await api.saveDoc(slug, draft)).page);
      closeEditor();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function saveManual() {
    if (!slug || manualDraft === null) return;
    setBusy(true);
    try {
      setPage((await api.saveDocManual(slug, manualDraft)).page);
      closeManual();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function resetPage() {
    if (!slug) return;
    setPending({ kind: "reset" });
  }

  /** Reset, then offer Undo. The backend snapshots the hand-edited text before the
   *  regeneration overwrites it (db.upsert_doc_page, reason "automatisch neu erzeugt"); Undo
   *  restores exactly that snapshot -- the newest version that did not exist before the reset. */
  async function resetWithUndo() {
    const target = slug;
    if (!target) return;
    setBusy(true);
    setError("");
    try {
      const before = new Set((await api.listDocVersions(target)).versions.map((v) => v.id));
      const { page: fresh } = await api.resetDoc(target);
      if (slugRef.current === target) setPage(fresh);
      const after = (await api.listDocVersions(target)).versions;
      if (slugRef.current === target && versionsOpen) setVersions(after);
      const snapshot = after.find((v) => !before.has(v.id));
      showToast({
        message: snapshot ? `„${fresh.title}“ neu erzeugt.` : `„${fresh.title}“ neu erzeugt (Text war unverändert).`,
        undo: snapshot && (async () => {
          try {
            const { page: restored } = await api.restoreDocVersion(target, snapshot.id);
            if (slugRef.current === target) {
              setPage(restored);
              if (versionsOpenRef.current) setVersions((await api.listDocVersions(target)).versions);
            }
          } catch (e) {
            fail(e);
          }
        }),
        timeoutMs: 12000,
      });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function confirmPending() {
    const action = pending;
    if (!action) return;
    if (action.kind === "all") await regenerate();
    else if (action.kind === "reset") await resetWithUndo();
    else await doRestore(action.version);
    setPending(null);
  }

  // The emergency chapter always comes first: it is the one people open under pressure.
  const ordered = [...pages.filter((p) => p.slug === NOTFALL), ...pages.filter((p) => p.slug !== NOTFALL)];
  const hasNotfall = ordered.length > 0 && ordered[0].slug === NOTFALL;
  const notesPresent = Boolean(page?.manualMd?.trim());

  const toc = (
    <nav className={`docs-toc${slug ? " has-chapter" : ""}`} aria-label="Kapitel">
      {!pagesLoaded ? (
        <div className="docs-toc-skeleton">
          {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} width={`${55 + ((i * 23) % 40)}%`} />)}
        </div>
      ) : ordered.length === 0 ? null : (
        <ul>
          {ordered.map((p) => (
            <li key={p.slug}>
              <Link to={`/dokumentation/${p.slug}`} aria-current={p.slug === slug ? "page" : undefined}
                    className={`docs-toc-link${p.slug === slug ? " active" : ""}${p.slug === NOTFALL ? " sos" : ""}`}>
                {p.slug === NOTFALL && <span className="docs-sos" aria-hidden="true">!</span>}
                <span>{p.title}</span>
                {p.slug === NOTFALL && <span className="visually-hidden"> (Notfall)</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );

  const regenerateAllItem = { label: "Alles neu erzeugen", onSelect: () => setPending({ kind: "all" }), disabled: busy };

  const landing = !pagesLoaded ? null : ordered.length === 0 ? (
    <div className="docs-empty">
      <p><strong>Noch keine Kapitel.</strong></p>
      <p className="muted">
        Die Dokumentation entsteht aus dem, was ein Netzwerk-Scan findet. {isAdmin
          ? "Starte einen Scan oder erzeuge sie jetzt aus dem bisherigen Bestand."
          : "Sobald jemand mit Admin-Rechten einen Scan durchführt, erscheinen hier die Kapitel."}
      </p>
      {isAdmin && (
        <div className="row">
          <button onClick={() => setPending({ kind: "all" })} disabled={busy}>Dokumentation erzeugen</button>
          <Link to="/scan" className="docs-link-button">Zum Netzwerk-Scan</Link>
        </div>
      )}
    </div>
  ) : (
    <div className="docs-landing">
      {hasNotfall && (
        <div className="docs-sos-callout">
          <div>
            <strong>Gerade funktioniert etwas nicht?</strong>
            <p className="muted">Die Notfall-Checkliste führt Schritt für Schritt durch – auch unter Zeitdruck.</p>
          </div>
          <button onClick={() => navigate(`/dokumentation/${NOTFALL}`)}>Zur Notfall-Checkliste</button>
        </div>
      )}
      <p className="muted docs-landing-hint">
        Nach Themen sortiert, in verständlicher Sprache – erzeugt aus dem, was HomeAtlas im Netzwerk
        gefunden hat. Wähle ein Kapitel.
      </p>
      {isAdmin && (
        <div className="row">
          <OverflowMenu items={[regenerateAllItem]} />
        </div>
      )}
    </div>
  );

  const meta = page ? [
    page.updatedAt ? `Stand: ${formatStand(page.updatedAt)}` : "",
    page.generated ? "automatisch erzeugt" : "von Hand bearbeitet",
    notesPresent ? "eigene Notiz vorhanden" : "",
  ].filter(Boolean).join(" · ") : "";

  const chapter = !page ? (
    <div className="docs-article" role="status" aria-live="polite">
      <span className="visually-hidden">Kapitel wird geladen …</span>
      <Skeleton width="55%" height={24} />
      <Skeleton width="40%" height={12} style={{ marginTop: 10 }} />
      <div style={{ marginTop: 24 }}><SkeletonText lines={6} /></div>
    </div>
  ) : (
    <article className="docs-article">
      <header className="docs-head">
        <div className="docs-head-row">
          <h1 className="docs-title">{page.title}</h1>
          {isAdmin && (
            <div className="docs-actions">
              {!editing ? (
                <>
                  <button className="secondary small" onClick={toggleVersions} aria-pressed={versionsOpen}>
                    {versionsOpen ? "Verlauf schließen" : "Verlauf"}
                  </button>
                  <button className="secondary small" onClick={() => { setDraft(page.bodyMd); setEditing(true); }}>
                    Bearbeiten
                  </button>
                  <OverflowMenu items={[
                    ...(page.generated === 0
                      ? [{ label: "Neu erzeugen", onSelect: () => void resetPage(), disabled: busy }]
                      : []),
                    regenerateAllItem,
                  ]} />
                </>
              ) : (
                <>
                  <button className="small" onClick={() => void save()} disabled={busy}>Speichern</button>
                  <button className="secondary small" onClick={closeEditor}>Abbrechen</button>
                </>
              )}
            </div>
          )}
        </div>
        <p className="docs-meta">{meta}</p>
      </header>

      {restoredDraft && (editing || manualDraft !== null) && (
        <div className={`notice ${draftIsStale ? "error" : "info"}`}>
          Ungespeicherter Entwurf aus dieser Sitzung wiederhergestellt.
          {draftIsStale && " Achtung: Das Kapitel wurde seitdem geändert (Scan oder Neu erzeugen). Speichern ersetzt den neueren Text; der landet dann im Verlauf."}
        </div>
      )}

      {versionsOpen && (
        <section className="docs-versions" aria-label="Verlauf dieser Seite">
          <h2>Verlauf</h2>
          {versions === null ? (
            <SkeletonText lines={3} />
          ) : versions.length === 0 ? (
            <p className="muted">
              Noch keine früheren Stände. Ab der ersten Änderung wird jeder vorherige Text hier gesichert.
            </p>
          ) : (
            <ul className="docs-version-list">
              {versions.map((v) => (
                <li key={v.id} className={preview?.id === v.id ? "active" : undefined}>
                  <div className="docs-version-text">
                    <span>{new Date(v.createdAt).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })}</span>
                    <small>{v.reason} · {Math.round(v.size / 100) / 10} kB</small>
                  </div>
                  <div className="docs-version-actions">
                    <button className="secondary small" onClick={() => void showVersion(v)}>Ansehen</button>
                    <button className="secondary small" disabled={busy} onClick={() => void restoreVersion(v)}>
                      Wiederherstellen
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {!preview && !editing && (manualDraft !== null || notesPresent || isAdmin) && (
        <section className="docs-notes" aria-label="Eigene Notizen">
          <div className="docs-notes-head">
            <h2>Eigene Notizen</h2>
            {isAdmin && (
              manualDraft === null ? (
                <button className="secondary small" onClick={() => setManualDraft(page.manualMd ?? "")}>
                  {notesPresent ? "Bearbeiten" : "Notiz hinzufügen"}
                </button>
              ) : (
                <div className="row">
                  <button className="small" onClick={() => void saveManual()} disabled={busy}>Speichern</button>
                  <button className="secondary small" onClick={closeManual}>Abbrechen</button>
                </div>
              )
            )}
          </div>
          {manualDraft !== null ? (
            <>
              <p className="muted docs-hint">
                Dieser Teil gehört dir. HomeAtlas ändert ihn <strong>nie</strong> automatisch – auch nicht
                beim Neuerzeugen. Alles darunter bleibt dagegen automatisch aktuell.
              </p>
              <textarea className="docs-textarea" style={{ minHeight: 200 }} autoFocus placeholder={NOTES_PLACEHOLDER}
                        aria-label="Eigene Notizen" value={manualDraft} onChange={(e) => changeManual(e.target.value)} />
            </>
          ) : notesPresent ? (
            <Markdown>{page.manualMd}</Markdown>
          ) : (
            <p className="muted docs-hint">
              Noch keine eigenen Notizen. Was hier steht, bleibt dauerhaft erhalten – Sicherungskästen,
              Standorte, Ansprechpartner, Eigenheiten, die kein Scan finden kann.
            </p>
          )}
        </section>
      )}

      {preview ? (
        <>
          <div className="notice info docs-preview-note">
            <span>
              Alter Stand vom <strong>{new Date(preview.createdAt).toLocaleString("de-DE")}</strong> ({preview.reason}).
              Nur eine Ansicht – die Seite selbst ist unverändert.
            </span>
            <button className="secondary small" onClick={() => setPreview(null)}>Zurück zum aktuellen Stand</button>
          </div>
          {preview.manualMd?.trim() && (
            <section className="docs-notes is-old" aria-label="Eigene Notizen (damaliger Stand)">
              <h2>Eigene Notizen (damaliger Stand)</h2>
              <Markdown>{preview.manualMd}</Markdown>
            </section>
          )}
          <Markdown>{preview.bodyMd ?? ""}</Markdown>
        </>
      ) : editing ? (
        <>
          <div className="notice info">{EDIT_WARNING}</div>
          <textarea className="docs-textarea" style={{ minHeight: 480 }} aria-label={`Text von „${page.title}“`}
                    value={draft} onChange={(e) => changeDraft(e.target.value)} />
        </>
      ) : (
        <Markdown>{page.bodyMd}</Markdown>
      )}
    </article>
  );


  return (
    <div className={`docs-page${slug ? " has-chapter" : ""}`}>
      {leaveDialog}
      {toast}
      <ConfirmDialog
        open={pending?.kind === "all"}
        title="Ganze Dokumentation neu erzeugen?"
        consequences={[
          "Alle automatisch erzeugten Kapitel werden aus dem aktuellen Gerätebestand neu geschrieben.",
          "Von Hand bearbeitete Kapitel und eigene Notizen bleiben, wie sie sind.",
          "Der bisherige Text jedes geänderten Kapitels wird im Verlauf gesichert.",
        ]}
        confirmLabel="Alles neu erzeugen"
        busy={busy}
        onConfirm={confirmPending}
        onCancel={() => setPending(null)}
      >
        <p className="muted">Mit KI-Unterstützung kann das einige Minuten dauern.</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={pending?.kind === "reset"}
        title={`„${page?.title ?? ""}“ neu erzeugen?`}
        consequences={[
          "Deine Handbearbeitung dieses Kapitels wird durch neu erzeugten Text ersetzt.",
          "Das Kapitel wird danach wieder automatisch aktuell gehalten.",
          "Eigene Notizen bleiben erhalten.",
        ]}
        confirmLabel="Kapitel neu erzeugen"
        danger
        busy={busy}
        onConfirm={confirmPending}
        onCancel={() => setPending(null)}
      >
        <p className="muted">Der bisherige Text landet im Verlauf; direkt danach kannst du es rückgängig machen.</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={pending?.kind === "restore"}
        title="Alten Stand wiederherstellen?"
        consequences={pending?.kind === "restore" ? [
          <>Das Kapitel bekommt den Text vom {new Date(pending.version.createdAt).toLocaleString("de-DE")} zurück.</>,
          "Die eigenen Notizen bleiben unverändert.",
          "Der aktuelle Text und die aktuellen Notizen werden vorher als Version gesichert.",
          "Das Kapitel gilt danach als von Hand bearbeitet und wird nicht mehr automatisch erneuert.",
        ] : []}
        confirmLabel="Wiederherstellen"
        busy={busy}
        onConfirm={confirmPending}
        onCancel={() => setPending(null)}
      />

      {error && <div className="notice error">{error}</div>}

      <div className="docs-layout">
        {toc}
        <div className="docs-main">
          {slug && ordered.length > 0 && (
            <label className="docs-picker">
              <span className="visually-hidden">Kapitel wählen</span>
              <span aria-hidden="true" className="docs-picker-label">Kapitel:</span>
              <select value={slug} onChange={(e) => leave(`/dokumentation/${e.target.value}`)}>
                {ordered.map((p) => (
                  <option key={p.slug} value={p.slug}>{p.slug === NOTFALL ? `! ${p.title}` : p.title}</option>
                ))}
              </select>
            </label>
          )}
          {slug ? chapter : landing}
        </div>
      </div>
    </div>
  );
}

const NOTES_PLACEHOLDER =
  "z. B.\n\n- Sicherung für den Serverschrank: Keller, Kasten links, F3\n" +
  "- Nach Stromausfall braucht der Switch ~5 Minuten, bevor WLAN wieder geht\n" +
  "- Wartungsvertrag Heizung: Firma Meier, 0123 456789";

const EDIT_WARNING = (
  <>
    Du bearbeitest hier den <strong>automatisch erzeugten</strong> Teil. Sobald du ihn von Hand
    speicherst, wird die ganze Seite beim nächsten Lauf nicht mehr aktualisiert — Gerätetabellen
    bleiben dann auf diesem Stand stehen. Für dauerhafte Ergänzungen sind meist die{" "}
    <strong>eigenen Notizen</strong> die bessere Wahl: die bleiben erhalten, während der Rest aktuell
    bleibt.
  </>
);
