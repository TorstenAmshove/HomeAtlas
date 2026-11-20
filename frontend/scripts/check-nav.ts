/**
 * Orphaned-route check, run by `npm run build` (and so by CI and the Docker build).
 *
 * Fails when:
 *  - a <Route path> in App.tsx has no entry in nav/config.ts ROUTES (a page without a menu home),
 *  - a ROUTES entry is not rendered by App.tsx (a menu entry pointing nowhere),
 *  - a pre-redesign route (LEGACY_ROUTES) is neither in ROUTES nor redirected to one,
 *  - a route names an area or tab that doesn't exist, or a tab links to an unknown route,
 *  - an area tab is admin-only while its route isn't, or the other way round.
 *
 * Plain Node with built-in type stripping (Node >= 22.18), no test framework needed.
 */
import { readFileSync } from "node:fs";
import { AREAS, LEGACY_ROUTES, REDIRECTS, ROUTES } from "../src/nav/config.ts";

const errors: string[] = [];
const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const rendered = new Set(
  [...appSource.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]).filter((p) => p !== "*"),
);
const configured = new Set(ROUTES.map((r) => r.path));

for (const path of rendered) {
  if (!configured.has(path)) errors.push(`App.tsx renders ${path}, but nav/config.ts ROUTES has no entry for it`);
}
for (const path of configured) {
  if (!rendered.has(path)) errors.push(`ROUTES lists ${path}, but App.tsx has no <Route path="${path}">`);
}
for (const path of LEGACY_ROUTES) {
  const target = configured.has(path) ? path : REDIRECTS[path];
  if (!target || !configured.has(target)) errors.push(`pre-redesign route ${path} has no home (not in ROUTES, no REDIRECTS target)`);
}

const routeByPath = new Map(ROUTES.map((r) => [r.path, r]));
for (const route of ROUTES) {
  const area = AREAS.find((a) => a.id === route.area);
  if (!area) { errors.push(`${route.path}: unknown area "${route.area}"`); continue; }
  if (route.tab && !area.tabs.some((t) => t.id === route.tab)) {
    errors.push(`${route.path}: area "${area.id}" has no tab "${route.tab}"`);
  }
  if (!route.tab && area.tabs.length > 0) errors.push(`${route.path}: area "${area.id}" has tabs, so the route must name one`);
}
for (const area of AREAS) {
  if (!routeByPath.has(area.path)) errors.push(`area "${area.id}" links to unknown route ${area.path}`);
  for (const tab of area.tabs) {
    const target = routeByPath.get(tab.path);
    if (!target) { errors.push(`tab ${area.id}/${tab.id} links to unknown route ${tab.path}`); continue; }
    if (Boolean(tab.adminOnly || area.adminOnly) !== Boolean(target.adminOnly)) {
      errors.push(`tab ${area.id}/${tab.id}: adminOnly differs from its route ${tab.path}`);
    }
  }
  // Every area must still show something to a member, or be admin-only as a whole.
  if (!area.adminOnly && area.tabs.length > 0 && area.tabs.every((t) => t.adminOnly)) {
    errors.push(`area "${area.id}" would be empty for members`);
  }
}

if (errors.length > 0) {
  console.error(`check-nav: ${errors.length} problem(s)\n  - ${errors.join("\n  - ")}`);
  process.exit(1);
}
console.log(`check-nav: ${ROUTES.length} routes in ${AREAS.length} areas, all ${LEGACY_ROUTES.length} pre-redesign routes have a home`);
