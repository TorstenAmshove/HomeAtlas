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
import { useUi } from "../shell/ui";

/**
 * Documentation chapters (Hilfe → Dokumentation).
 *
 * Unsaved text -- the "Bearbeiten" draft and the "Eigene Notizen" draft -- is kept per chapter in
 * sessionStorage (lib/drafts.ts) and restored when the chapter is opened again; leaving with unsaved
 * changes asks first (lib/useLeaveGuard.tsx). Both apply to the old and the new UI: losing a draft
 * by clicking another chapter was a bug, not a design choice (forensics "Dokumentation" 1).
 *
 * With the new shell (`useUi().calm`) the page renders the redesigned layout below; otherwise the
 * pre-redesign markup, unchanged apart from the draft handling.
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
  const { calm } = useUi();
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
  // Old UI: history panel open in component state. New UI: `?versions=1`, so Back/reload keep it.
  const [versionsLocal, setVersionsLocal] = useState(false);
  const [versionsParam, setVersionsParam] = useUrlState("versions");
  const versionsOpen = calm ? versionsParam === "1" : versionsLocal;
  const [pending, setPending] = useState<Pending>(null);
  const [toast, showToast] = useUndoToast();
  const slugRef = useRef(slug);
  slugRef.current = slug;

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
    setVersionsLocal(false);
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
    setEditing(bodyDraft !== null);
    setDraft(bodyDraft ?? "");
    setManualDraft(notesDraft);
    setRestoredDraft(bodyDraft !== null || notesDraft !== null);
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
    if (calm) setVersionsParam(versionsOpen ? "" : "1", { push: true });
    else setVersionsLocal((open) => !open);
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

  async function restoreVersion(version: DocVersion) {
    if (calm) {
      setPending({ kind: "restore", version });
      return;
    }
    const when = new Date(version.createdAt).toLocaleString("de-DE");
    if (!window.confirm(`Stand vom ${when} wiederherstellen? Der aktuelle Text wird vorher als Version gesichert.`)) return;
    await doRestore(version);
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

  function changeDraft(value: string) {
    setDraft(value);
    if (slug) writeDraft(draftKeys.docBody(slug), value);
  }

  function closeEditor() {
    setEditing(false);
    setRestoredDraft(false);
    if (slug) writeDraft(draftKeys.docBody(slug), null);
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
    if (calm) {
      setPending({ kind: "reset" });
      return;
    }
    if (!window.confirm("Diese Seite neu erzeugen? Deine eigenen Änderungen an dieser Seite gehen dabei verloren.")) return;
    setBusy(true);
    try {
      setPage((await api.resetDoc(slug)).page);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  /** New UI: reset, then offer Undo. The backend snapshots the hand-edited text before the
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
              if (versionsOpen) setVersions((await api.listDocVersions(target)).versions);
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

  // ----------------------------------------------------------------------------------- old UI

  if (!calm) {
    return (
      <>
        {leaveDialog}
        <div className="page-header">
          <div>
            <h1>Dokumentation</h1>
            <p>
              Nach Themen sortiert und in verständlicher Sprache — erzeugt aus dem, was HomeAtlas im
              Netzwerk gefunden hat. Jede Seite lässt sich von Hand überarbeiten.
            </p>
          </div>
          {isAdmin && (
            <button className="secondary" onClick={() => void regenerate()} disabled={busy}>
              {busy ? "Erzeuge…" : "Alles neu erzeugen"}
            </button>
          )}
        </div>

        {error && <div className="notice error">{error}</div>}

        <div style={{ display: "flex", gap: 20, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div className="card" style={{ flex: "0 0 260px", minWidth: 240 }}>
            <h2 style={{ fontSize: "0.9rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-muted)" }}>
              Kapitel
            </h2>
            {pages.length === 0 ? (
              <p className="muted">Noch keine Kapitel. Führe einen Netzwerk-Scan durch.</p>
            ) : (
              pages.map((p) => (
                <Link
                  key={p.slug}
                  to={`/dokumentation/${p.slug}`}
                  className="nav-link"
                  style={{
                    background: p.slug === slug ? "var(--bg-hover)" : undefined,
                    color: p.slug === slug ? "var(--text)" : undefined,
                  }}
                >
                  {p.title}
                </Link>
              ))
            )}
          </div>

          <div style={{ flex: 1, minWidth: 300 }}>
            {!slug ? (
              <div className="card">
                <h2>Wähle links ein Kapitel</h2>
                <p className="muted">
                  Wenn gerade etwas nicht funktioniert, ist <strong>„Wenn etwas nicht funktioniert"</strong> der
                  richtige Einstieg — dort steht eine Checkliste, der man auch unter Zeitdruck folgen kann.
                </p>
                {pages.some((p) => p.slug === NOTFALL) && (
                  <button onClick={() => navigate(`/dokumentation/${NOTFALL}`)}>Zur Notfall-Checkliste</button>
                )}
              </div>
            ) : !page ? (
              <span className="spinner" />
            ) : (
              <div className="card">
                <div className="row" style={{ justifyContent: "space-between", marginBottom: 14 }}>
                  <h2 style={{ margin: 0 }}>{page.title}</h2>
                  {isAdmin && (
                    <div className="row">
                      {page.generated === 0 && <span className="badge warn">von Hand bearbeitet</span>}
                      {!editing ? (
                        <>
                          <button className="secondary small" onClick={toggleVersions}>
                            {versions ? "Verlauf schließen" : "Verlauf"}
                          </button>
                          <button className="secondary small" onClick={() => { setDraft(page.bodyMd); setEditing(true); }}>
                            Bearbeiten
                          </button>
                          {page.generated === 0 && (
                            <button className="secondary small" onClick={() => void resetPage()} disabled={busy}>
                              Neu erzeugen
                            </button>
                          )}
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

                {restoredDraft && (editing || manualDraft !== null) && (
                  <div className="notice info">Ungespeicherter Entwurf aus dieser Sitzung wiederhergestellt.</div>
                )}

                {versions && (
                  <div className="card" style={{ background: "var(--bg)" }}>
                    <h3 style={{ marginTop: 0 }}>Verlauf dieser Seite</h3>
                    {versions.length === 0 ? (
                      <p className="muted" style={{ marginBottom: 0 }}>
                        Noch keine früheren Stände. Ab der ersten Änderung wird jeder vorherige Text
                        hier gesichert.
                      </p>
                    ) : (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr><th>Zeitpunkt</th><th>Anlass</th><th>Umfang</th><th /></tr>
                          </thead>
                          <tbody>
                            {versions.map((v) => (
                              <tr key={v.id}>
                                <td>{new Date(v.createdAt).toLocaleString("de-DE")}</td>
                                <td className="muted">{v.reason}</td>
                                <td className="muted">{Math.round(v.size / 100) / 10} kB</td>
                                <td style={{ whiteSpace: "nowrap", width: 1 }}>
                                  <button className="secondary small" onClick={() => void showVersion(v)}>Ansehen</button>{" "}
                                  <button className="secondary small" disabled={busy}
                                          onClick={() => void restoreVersion(v)}>Wiederherstellen</button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                )}

                {!preview && !editing && (manualDraft !== null || page.manualMd?.trim() || isAdmin) && (
                  <div
                    className="card"
                    style={{
                      background: "var(--bg)",
                      borderLeft: "3px solid var(--accent-strong)",
                      marginBottom: 20,
                    }}
                  >
                    <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
                      <h3 style={{ margin: 0 }}>Eigene Notizen</h3>
                      {isAdmin && (
                        manualDraft === null ? (
                          <button className="secondary small" onClick={() => setManualDraft(page.manualMd ?? "")}>
                            {page.manualMd?.trim() ? "Bearbeiten" : "Notiz hinzufügen"}
                          </button>
                        ) : (
                          <div className="row">
                            <button className="small" onClick={() => void saveManual()} disabled={busy}>
                              Speichern
                            </button>
                            <button className="secondary small" onClick={closeManual}>
                              Abbrechen
                            </button>
                          </div>
                        )
                      )}
                    </div>

                    {manualDraft !== null ? (
                      <>
                        <div className="notice info">
                          Dieser Teil gehört dir. Er wird von HomeAtlas <strong>nie</strong> automatisch
                          geändert oder überschrieben — auch nicht beim Neuerzeugen der Dokumentation.
                          Alles darunter bleibt dagegen automatisch aktuell.
                        </div>
                        <textarea
                          style={{ minHeight: 220 }}
                          autoFocus
                          placeholder={NOTES_PLACEHOLDER}
                          value={manualDraft}
                          onChange={(e) => changeManual(e.target.value)}
                        />
                      </>
                    ) : page.manualMd?.trim() ? (
                      <Markdown>{page.manualMd}</Markdown>
                    ) : (
                      <p className="muted" style={{ margin: 0 }}>
                        Noch keine eigenen Notizen zu diesem Kapitel. Was hier steht, bleibt dauerhaft
                        erhalten — Sicherungskästen, Standorte, Ansprechpartner, Eigenheiten, die kein
                        Scan finden kann.
                      </p>
                    )}
                  </div>
                )}

                {preview ? (
                  <>
                    <div className="notice info">
                      Alter Stand vom <strong>{new Date(preview.createdAt).toLocaleString("de-DE")}</strong> ({preview.reason}).
                      Dies ist nur eine Ansicht — die Seite selbst ist unverändert.{" "}
                      <button className="secondary small" onClick={() => setPreview(null)}>Zurück zum aktuellen Stand</button>
                    </div>
                    {preview.manualMd?.trim() && (
                      <div className="card" style={{ background: "var(--bg)", borderLeft: "3px solid var(--border)" }}>
                        <h3 style={{ marginTop: 0 }}>Eigene Notizen (damaliger Stand)</h3>
                        <Markdown>{preview.manualMd}</Markdown>
                      </div>
                    )}
                    <Markdown>{preview.bodyMd ?? ""}</Markdown>
                  </>
                ) : editing ? (
                  <>
                    <div className="notice info">{EDIT_WARNING}</div>
                    <textarea style={{ minHeight: 480 }} value={draft} onChange={(e) => changeDraft(e.target.value)} />
                  </>
                ) : (
                  <Markdown>{page.bodyMd}</Markdown>
                )}
              </div>
            )}
          </div>
        </div>
      </>
    );
  }

  // ----------------------------------------------------------------------------------- new UI

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
        <div className="notice info">Ungespeicherter Entwurf aus dieser Sitzung wiederhergestellt.</div>
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
    <div className={`docs-calm${slug ? " has-chapter" : ""}`}>
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
          "Der aktuelle Text wird vorher als Version gesichert.",
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
