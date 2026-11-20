import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, CornerDownLeft, FileText, Search, X } from "lucide-react";
import { api, type DocPage, type System } from "../lib/api";
import { matchesDeviceQuery } from "../lib/search";
import { KindIcon } from "../lib/icons";
import { SEARCH_SOURCES } from "../nav/config";
import { Skeleton } from "../components/Skeleton";
import { pageEntries } from "./navMatch";

/**
 * ⌘K / Ctrl+K search over everything in SEARCH_SOURCES (docs/redesign/5-information-architecture.md):
 * pages (role-filtered), devices (same matcher as the device list, so both find the same things)
 * and documentation chapter titles. Data is fetched when the palette opens, not before, so the
 * shell costs no extra requests on pages where nobody searches. On phones the same component is
 * full-screen (CSS).
 */

type Source = (typeof SEARCH_SOURCES)[number];

interface Result {
  key: string;
  source: Source;
  label: string;
  sub: string;
  path: string;
  kind?: string;
}

const SOURCE_LABEL: Record<Source, string> = {
  pages: "Seiten",
  devices: "Geräte",
  docChapters: "Dokumentation",
};

const LIMIT: Record<Source, number> = { pages: 8, devices: 8, docChapters: 6 };

export default function CommandPalette({ open, isAdmin, onClose }: {
  open: boolean;
  isAdmin: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [systems, setSystems] = useState<System[] | null>(null);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [docs, setDocs] = useState<Omit<DocPage, "bodyMd">[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!open) {
      // Reset on close, not on open: a key typed right after ⌘K must not be wiped by a late reset.
      setQuery("");
      setActive(0);
      return;
    }
    setLoadError(false);
    // Fresh on every open: devices come and go with scans; it is one request each.
    let cancelled = false;
    api.listSystems()
      .then((r) => { if (!cancelled) { setSystems(r.systems); setKindLabels(r.kindLabels); } })
      .catch(() => { if (!cancelled) { setSystems([]); setLoadError(true); } });
    api.listDocs()
      .then((r) => { if (!cancelled) setDocs(r.pages); })
      .catch(() => { if (!cancelled) { setDocs([]); setLoadError(true); } });
    return () => { cancelled = true; };
  }, [open]);

  const results = useMemo<Result[]>(() => {
    const needle = query.trim().toLowerCase();
    const out: Result[] = [];
    for (const source of SEARCH_SOURCES) {
      let items: Result[] = [];
      if (source === "pages") {
        items = pageEntries(isAdmin)
          .filter((p) => !needle || `${p.label} ${p.keywords}`.toLowerCase().includes(needle))
          .map((p) => ({ key: `page:${p.path}`, source, label: p.label, sub: p.context, path: p.path }));
      } else if (!needle) {
        continue; // Without a query the palette is a page switcher; devices/docs need a word.
      } else if (source === "devices") {
        items = (systems ?? [])
          .filter((s) => matchesDeviceQuery(s, needle))
          .map((s) => ({
            key: `device:${s.id}`, source, label: s.name || s.ip || s.hostname,
            sub: [s.ip, kindLabels[s.kind] ?? s.kind, s.location].filter(Boolean).join(" · "),
            path: `/geraete/${s.id}`, kind: s.kind,
          }));
      } else if (source === "docChapters") {
        items = (docs ?? [])
          .filter((d) => d.title.toLowerCase().includes(needle))
          .map((d) => ({ key: `doc:${d.slug}`, source, label: d.title, sub: "Kapitel", path: `/dokumentation/${d.slug}` }));
      }
      out.push(...items.slice(0, LIMIT[source]));
    }
    return out;
  }, [query, systems, docs, kindLabels, isAdmin]);

  useEffect(() => { setActive(0); }, [query]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const loading = Boolean(query.trim()) && (systems === null || docs === null);

  function go(result: Result | undefined) {
    if (!result) return;
    onClose();
    navigate(result.path);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, Math.max(results.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Home") {
      setActive(0);
    } else if (event.key === "End") {
      setActive(Math.max(results.length - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(results[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  let lastSource: Source | null = null;

  return (
    <div className="palette-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Suche" onKeyDown={onKeyDown}>
        <div className="palette-input">
          <Search size={18} aria-hidden="true" />
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Gerät, IP, Kapitel oder Seite suchen …"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-results"
            aria-activedescendant={results[active] ? `palette-${active}` : undefined}
            aria-autocomplete="list"
            autoComplete="off"
            spellCheck={false}
          />
          <button type="button" className="sbtn icon-button" onClick={onClose} aria-label="Suche schließen">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="palette-results" id="palette-results" role="listbox" ref={listRef} aria-label="Treffer">
          {results.map((result, index) => {
            const heading = result.source !== lastSource ? SOURCE_LABEL[result.source] : null;
            lastSource = result.source;
            return (
              <div key={result.key} role="presentation">
                {heading && <div className="palette-group" role="presentation">{heading}</div>}
                <div
                  id={`palette-${index}`}
                  data-index={index}
                  role="option"
                  aria-selected={index === active}
                  className={`palette-item${index === active ? " active" : ""}`}
                  onMouseMove={() => setActive(index)}
                  onClick={() => go(result)}
                >
                  <span className="palette-icon" aria-hidden="true">
                    {result.source === "devices" ? <KindIcon kind={result.kind ?? "other"} size={16} />
                      : result.source === "docChapters" ? <BookOpen size={16} /> : <FileText size={16} />}
                  </span>
                  <span className="palette-text">
                    <span className="palette-label">{result.label}</span>
                    {result.sub && <span className="palette-sub">{result.sub}</span>}
                  </span>
                  {index === active && <CornerDownLeft size={14} className="palette-enter" aria-hidden="true" />}
                </div>
              </div>
            );
          })}
          {loading && (
            <div className="palette-loading" aria-hidden="true">
              <Skeleton width="60%" /><Skeleton width="40%" />
            </div>
          )}
          {!loading && query.trim() && results.length === 0 && (
            <div className="palette-empty">Nichts gefunden für „{query.trim()}“.</div>
          )}
          {loadError && <div className="palette-empty">Geräte oder Kapitel konnten nicht geladen werden.</div>}
        </div>
        <div className="palette-hint" aria-hidden="true">
          <span><kbd>↑</kbd><kbd>↓</kbd> wählen</span><span><kbd>↵</kbd> öffnen</span><span><kbd>Esc</kbd> schließen</span>
        </div>
      </div>
    </div>
  );
}
