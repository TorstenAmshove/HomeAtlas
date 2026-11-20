import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, BookOpen, Ellipsis, Home, KeyRound, LogOut, Search, Server, type LucideIcon } from "lucide-react";
import { api, type User } from "../lib/api";
import { visibleAreas, type IconName } from "../nav/config";
import { PageSkeleton, Skeleton } from "../components/Skeleton";
import CommandPalette from "./CommandPalette";
import { locate } from "./navMatch";
import { useUi } from "./ui";
import type { ThemeMode } from "./prefs";
import "./shell.css";
import "./hilfe.css";

/**
 * The redesigned app frame (docs/redesign/5-information-architecture.md), shown when `uiCalm` is on.
 * Everything in the menu comes from nav/config.ts: the sidebar (desktop) and the bottom bar (phone)
 * list the areas, the active area's tabs sit in the top bar. It renders the same page components
 * as the old frame; it only changes what is around them.
 *
 * Theme tokens live in shell.css under `body:has(.app-shell)`, so nothing here leaks into the old UI.
 */

const ICONS: Record<IconName, LucideIcon> = { Home, Server, BookOpen, KeyRound, Ellipsis };

const THEME_COLOR = { light: "#fafaf9", dark: "#161615" } as const;

function useResolvedTheme(mode: ThemeMode): "light" | "dark" {
  const query = "(prefers-color-scheme: dark)";
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const onChange = () => setSystemDark(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return mode === "system" ? (systemDark ? "dark" : "light") : mode;
}

/** theme-color follows the mode; viewport-fit=cover enables the safe-area insets. Both are put
 *  back when the shell unmounts, so the old UI keeps its exact <head>. */
function useDocumentChrome(theme: "light" | "dark") {
  // The page's own theme-color (index.html), read once on mount and put back on unmount, so it can't
  // drift from a hard-coded copy.
  useEffect(() => {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    const original = meta?.getAttribute("content") ?? null;
    return () => { if (meta && original !== null) meta.setAttribute("content", original); };
  }, []);
  useEffect(() => {
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
  }, [theme]);
  useEffect(() => {
    const viewport = document.querySelector<HTMLMetaElement>('meta[name="viewport"]');
    const previous = viewport?.getAttribute("content") ?? null;
    if (viewport && previous && !previous.includes("viewport-fit")) {
      viewport.setAttribute("content", `${previous}, viewport-fit=cover`);
    }
    return () => { if (viewport && previous !== null) viewport.setAttribute("content", previous); };
  }, []);
}

function Brand({ homeName }: { homeName: string | null }) {
  return (
    <Link to="/" className="shell-brand" aria-label="HomeAtlas – zur Startseite">
      <img src="/icon.svg" alt="" width={28} height={28} />
      <span className="shell-brand-name">{homeName ?? <Skeleton width={110} />}</span>
    </Link>
  );
}

export default function AppShell({ user, isAdmin, onLogout, children }: {
  user: User;
  isAdmin: boolean;
  onLogout: () => Promise<void>;
  children: ReactNode;
}) {
  const { themeMode } = useUi();
  const theme = useResolvedTheme(themeMode);
  useDocumentChrome(theme);

  const location = useLocation();
  const navigate = useNavigate();
  const areas = visibleAreas(isAdmin);
  const here = locate(location.pathname, isAdmin);
  const [searchOpen, setSearchOpen] = useState(false);
  const [homeName, setHomeName] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings()
      .then((r) => setHomeName(String(r.settings.homeName || "HomeAtlas")))
      .catch(() => setHomeName("HomeAtlas"));
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // A new page starts at the top, as a new page would in the old frame.
  useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);

  const closeSearch = useCallback(() => setSearchOpen(false), []);

  const title = here.area?.id === "start" ? homeName ?? "" : here.route?.title ?? "HomeAtlas";
  const roleLabel = isAdmin ? "Administrator" : "Mitglied (nur lesen)";
  const displayName = user.displayName || user.username;
  const isChat = location.pathname === "/assistent" || location.pathname.startsWith("/assistent/");

  function goBack(fallback: string) {
    // "Back lands where you were" (filters in the URL included); a deep link has nothing to go
    // back to inside the app, so it falls back to the list.
    if (location.key !== "default") navigate(-1);
    else navigate(fallback);
  }

  const tabRow = here.area && here.area.tabs.length > 0 && (
    <nav className="shell-tabs" aria-label={`${here.area.label}: Bereiche`}>
      {here.area.tabs.map((tab) => (
        <NavLink key={tab.id} to={tab.path}
                 className={() => `shell-tab${here.tab?.id === tab.id ? " active" : ""}`}
                 aria-current={here.tab?.id === tab.id ? "page" : undefined}>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className={`app-shell${isChat ? " is-chat" : ""}`} data-theme={theme}>
      <a href="#shell-content" className="skip-link">Zum Inhalt springen</a>

      <aside className="shell-side" aria-label="Hauptmenü">
        <Brand homeName={homeName} />
        <nav className="shell-areas">
          {areas.map((area) => {
            const Icon = ICONS[area.icon];
            const active = here.area?.id === area.id;
            return (
              <Link key={area.id} to={area.path} className={`shell-area${active ? " active" : ""}`}
                    aria-current={active ? "page" : undefined}>
                <Icon size={18} aria-hidden="true" />
                {area.label}
              </Link>
            );
          })}
        </nav>
        <div className="shell-side-foot">
          <div>Angemeldet als <strong>{displayName}</strong></div>
          <div className="shell-muted">{roleLabel}</div>
          <button type="button" className="sbtn shell-logout" onClick={() => void onLogout()}>
            <LogOut size={14} aria-hidden="true" /> Abmelden
          </button>
        </div>
      </aside>

      <div className="shell-main">
        <header className="shell-top">
          <div className="shell-top-row">
            <div className="shell-title">{title || <Skeleton width={140} height={18} />}</div>
            <div className="shell-top-tabs">
              {here.list ? (
                <button type="button" className="sbtn shell-back shell-back-desktop" onClick={() => goBack(here.list!.path)}>
                  <ArrowLeft size={16} aria-hidden="true" /> {here.list.label}
                </button>
              ) : null}
              {tabRow}
            </div>
            <button type="button" className="sbtn shell-search" onClick={() => setSearchOpen(true)}
                    aria-label="Suchen" aria-keyshortcuts="Control+K Meta+K">
              <Search size={16} aria-hidden="true" />
              <span className="shell-search-label">Suchen …</span>
              <kbd className="shell-search-kbd">{/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘K" : "Strg K"}</kbd>
            </button>
          </div>
          {/* Phone: one second row, either the area's tabs or "← list" on detail pages. */}
          <div className="shell-top-sub">
            {here.list ? (
              <button type="button" className="sbtn shell-back" onClick={() => goBack(here.list!.path)}>
                <ArrowLeft size={18} aria-hidden="true" /> {here.list.label}
              </button>
            ) : tabRow}
          </div>
        </header>

        {here.area?.id === "mehr" && (
          <div className="shell-account" aria-label="Konto">
            <span>Angemeldet als <strong>{displayName}</strong> · {roleLabel}</span>
            <button type="button" className="sbtn shell-logout" onClick={() => void onLogout()}>
              <LogOut size={16} aria-hidden="true" /> Abmelden
            </button>
          </div>
        )}

        <main id="shell-content" className="shell-content" tabIndex={-1}>
          <Suspense fallback={<PageSkeleton />}>{children}</Suspense>
        </main>
      </div>

      <nav className="shell-bottom" aria-label="Hauptmenü">
        {areas.map((area) => {
          const Icon = ICONS[area.icon];
          const active = here.area?.id === area.id;
          return (
            <Link key={area.id} to={area.path} className={`shell-bottom-item${active ? " active" : ""}`}
                  aria-current={active ? "page" : undefined}>
              <Icon size={22} aria-hidden="true" />
              <span>{area.label}</span>
            </Link>
          );
        })}
      </nav>

      <CommandPalette open={searchOpen} isAdmin={isAdmin} onClose={closeSearch} />
    </div>
  );
}

/** Loading screen in the new shell's shape, shown while App.tsx waits for the session and health
 *  (only when this browser last saw the new shell; otherwise the old spinner stays). */
export function ShellSkeleton() {
  const theme = useResolvedTheme(useUi().themeMode);
  return (
    <div className="app-shell" data-theme={theme}>
      <aside className="shell-side">
        <div className="shell-brand"><Skeleton width={28} height={28} radius={7} /><Skeleton width={110} /></div>
        <div className="shell-areas" style={{ gap: 14, padding: "8px 10px" }}>
          {[60, 70, 50, 72, 48].map((w, i) => <Skeleton key={i} width={w} />)}
        </div>
      </aside>
      <div className="shell-main">
        <header className="shell-top"><div className="shell-top-row"><Skeleton width={160} height={18} /></div></header>
        <main className="shell-content"><PageSkeleton /></main>
      </div>
    </div>
  );
}
