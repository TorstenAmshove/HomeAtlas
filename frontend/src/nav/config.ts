/**
 * The one place that defines the app's menu: areas, their tabs, and which area every route
 * belongs to (docs/redesign/5-information-architecture.md).
 *
 * Pure data on purpose -- no React, no imports -- so `scripts/check-nav.ts` can load it with plain
 * Node during `npm run build` and fail the build when a route has no home. Role gating here is
 * only for *showing* entries; the route guard in App.tsx and `require_admin` on the backend stay
 * the actual enforcement, exactly as before.
 */

export type AreaId = "start" | "geraete" | "hilfe" | "zugaenge" | "mehr";

/** Lucide icon names; the shell maps them to components. */
export type IconName = "Home" | "Server" | "BookOpen" | "KeyRound" | "Ellipsis";

export interface Tab {
  id: string;
  label: string;
  /** Where the tab links to. */
  path: string;
  adminOnly?: boolean;
}

export interface Area {
  id: AreaId;
  label: string;
  icon: IconName;
  /** Where clicking the area itself goes (normally its first tab). */
  path: string;
  adminOnly?: boolean;
  /** Tabs shown in the top bar while the area is active. Empty = no tab row. */
  tabs: Tab[];
}

/** Order = order in the sidebar and in the phone's bottom bar (usage-audit ranking). */
export const AREAS: Area[] = [
  { id: "start", label: "Start", icon: "Home", path: "/", tabs: [] },
  {
    id: "geraete", label: "Geräte", icon: "Server", path: "/geraete",
    tabs: [
      { id: "liste", label: "Liste", path: "/geraete" },
      { id: "plan", label: "Netzplan", path: "/plan" },
      { id: "netze", label: "Netze & WLAN", path: "/netze" },
    ],
  },
  {
    id: "hilfe", label: "Hilfe", icon: "BookOpen", path: "/dokumentation",
    tabs: [
      { id: "doku", label: "Dokumentation", path: "/dokumentation" },
      { id: "assistent", label: "Assistent", path: "/assistent" },
    ],
  },
  { id: "zugaenge", label: "Zugänge", icon: "KeyRound", path: "/zugaenge", adminOnly: true, tabs: [] },
  {
    // "Mehr": rarely used pages. They move here, they don't disappear.
    id: "mehr", label: "Mehr", icon: "Ellipsis", path: "/einstellungen",
    tabs: [
      { id: "scan", label: "Scan", path: "/scan", adminOnly: true },
      { id: "benutzer", label: "Benutzer", path: "/benutzer", adminOnly: true },
      { id: "protokoll", label: "Protokoll", path: "/protokoll", adminOnly: true },
      { id: "einstellungen", label: "Einstellungen", path: "/einstellungen" },
    ],
  },
];

export interface RouteEntry {
  /** react-router path pattern, exactly as in <Route path>. */
  path: string;
  area: AreaId;
  /** Tab that is highlighted on this route (detail pages highlight their list's tab). */
  tab?: string;
  title: string;
  adminOnly?: boolean;
  /**
   * A `:param` route that switches between siblings inside its tab (a doc chapter, a conversation)
   * rather than drilling into a detail page: the shell keeps the tab row and shows no "← list".
   */
  sibling?: boolean;
  /** A static path that is still a detail page of its list (`/zugaenge/neu`): "← list" like `:id` routes. */
  detail?: boolean;
}

/** Every routed page. scripts/check-nav.ts compares this with App.tsx in both directions. */
export const ROUTES: RouteEntry[] = [
  { path: "/", area: "start", title: "Start" },
  { path: "/geraete", area: "geraete", tab: "liste", title: "Geräte" },
  { path: "/geraete/:id", area: "geraete", tab: "liste", title: "Gerät" },
  { path: "/plan", area: "geraete", tab: "plan", title: "Netzplan" },
  { path: "/netze", area: "geraete", tab: "netze", title: "Netze & WLAN" },
  { path: "/dokumentation", area: "hilfe", tab: "doku", title: "Dokumentation" },
  { path: "/dokumentation/:slug", area: "hilfe", tab: "doku", title: "Dokumentation", sibling: true },
  { path: "/assistent", area: "hilfe", tab: "assistent", title: "Assistent" },
  { path: "/assistent/:chatId", area: "hilfe", tab: "assistent", title: "Assistent", sibling: true },
  { path: "/zugaenge", area: "zugaenge", title: "Zugänge", adminOnly: true },
  { path: "/zugaenge/neu", area: "zugaenge", title: "Neuer Zugang", adminOnly: true, detail: true },
  { path: "/zugaenge/:id", area: "zugaenge", title: "Zugang", adminOnly: true },
  { path: "/scan", area: "mehr", tab: "scan", title: "Netzwerk-Scan", adminOnly: true },
  { path: "/benutzer", area: "mehr", tab: "benutzer", title: "Benutzer", adminOnly: true },
  { path: "/protokoll", area: "mehr", tab: "protokoll", title: "Protokoll", adminOnly: true },
  { path: "/einstellungen", area: "mehr", tab: "einstellungen", title: "Einstellungen" },
];

/**
 * The routes that existed before the redesign (docs/redesign/4-route-map.md), frozen. Nothing may
 * disappear: each must stay in ROUTES, or be listed in REDIRECTS with a target that is.
 */
export const LEGACY_ROUTES: readonly string[] = [
  "/", "/geraete", "/geraete/:id", "/plan", "/netze", "/dokumentation", "/dokumentation/:slug",
  "/assistent", "/zugaenge", "/scan", "/benutzer", "/protokoll", "/einstellungen",
];

/** Old path -> new path, for routes that move. Empty so far. */
export const REDIRECTS: Record<string, string> = {};

/**
 * What ⌘K searches. Devices use exactly the fields the device-list search has always used, so
 * the new search finds everything the old one did (lib/search.ts uses this same list).
 */
export const DEVICE_SEARCH_FIELDS = [
  "name", "hostname", "ip", "mac", "vendor", "model", "location", "purpose",
] as const;

export const SEARCH_SOURCES = ["pages", "devices", "docChapters"] as const;

export function areaOf(routePath: string): Area | undefined {
  const entry = ROUTES.find((r) => r.path === routePath);
  return entry && AREAS.find((a) => a.id === entry.area);
}

export function visibleAreas(isAdmin: boolean): Area[] {
  return AREAS.filter((a) => isAdmin || !a.adminOnly).map((a) => ({
    ...a,
    tabs: a.tabs.filter((t) => isAdmin || !t.adminOnly),
  }));
}
