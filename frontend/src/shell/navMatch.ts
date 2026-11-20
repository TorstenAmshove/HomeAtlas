import { matchPath } from "react-router-dom";
import { AREAS, ROUTES, visibleAreas, type Area, type RouteEntry, type Tab } from "../nav/config";

/** The ROUTES entry for a concrete pathname (static paths win over `:param` ones). */
export function routeFor(pathname: string): RouteEntry | undefined {
  const exact = ROUTES.find((r) => !r.path.includes(":") && matchPath({ path: r.path, end: true }, pathname));
  return exact ?? ROUTES.find((r) => matchPath({ path: r.path, end: true }, pathname));
}

export function isDetailRoute(route: RouteEntry | undefined): boolean {
  return Boolean(route?.path.includes(":"));
}

export interface Location {
  route?: RouteEntry;
  area?: Area;
  tab?: Tab;
  /** For detail routes: the list they belong to ("← Geräte"). */
  list?: { path: string; label: string };
}

/** Area, tab and parent list for a pathname, as the given role sees them. */
export function locate(pathname: string, isAdmin: boolean): Location {
  const route = routeFor(pathname);
  if (!route) return {};
  const area = visibleAreas(isAdmin).find((a) => a.id === route.area)
    ?? AREAS.find((a) => a.id === route.area);
  const tab = area?.tabs.find((t) => t.id === route.tab);
  let list: Location["list"];
  if (isDetailRoute(route)) {
    const listPath = tab?.path ?? area?.path ?? "/";
    const listRoute = ROUTES.find((r) => r.path === listPath);
    list = { path: listPath, label: listRoute?.title ?? tab?.label ?? area?.label ?? "Zurück" };
  }
  return { route, area, tab, list };
}

export interface PageEntry {
  path: string;
  label: string;
  /** Area name, shown as context ("Mehr"). */
  context: string;
  /** Extra words the search matches (the route's own title, e.g. "Netzwerk-Scan" for "Scan"). */
  keywords: string;
}

/** Every page the role can open, for the ⌘K search. Detail routes are reached via their data. */
export function pageEntries(isAdmin: boolean): PageEntry[] {
  const entries: PageEntry[] = [];
  for (const area of visibleAreas(isAdmin)) {
    const targets = area.tabs.length > 0 ? area.tabs : [{ id: area.id, label: area.label, path: area.path }];
    for (const target of targets) {
      const route = ROUTES.find((r) => r.path === target.path);
      entries.push({
        path: target.path,
        label: target.label,
        // A tab says which area it belongs to; an area without tabs is its own page.
        context: area.tabs.length > 0 ? area.label : "",
        keywords: `${route?.title ?? ""} ${area.label}`,
      });
    }
  }
  return entries;
}
