import type { System } from "../../lib/api";
import { matchesDeviceQuery } from "../../lib/search";

/**
 * Filtering and sorting of the device list, shared by the classic InventoryPage and the new
 * InventoryCalm so both read the same URL (`q`, `sort`, `kind`, `project`, `parentId`, `status`,
 * `importance`; docs/redesign/5-information-architecture.md, "Zustand in der URL") the same way.
 * Pure functions over the `GET /api/systems` list: no counts are fetched separately.
 */

export const STATUS_LABEL: Record<string, string> = {
  online: "erreichbar",
  offline: "nicht erreichbar",
  unknown: "unbekannt",
};

export const IMPORTANCE_LABEL: Record<string, string> = {
  critical: "kritisch",
  normal: "normal",
  low: "gering",
};

export type SortKey = "name" | "ip" | "kind" | "location" | "status";
export interface Sort { key: SortKey; dir: "asc" | "desc" }

const SORT_KEYS: readonly SortKey[] = ["name", "ip", "kind", "location", "status"];

/** `?sort=name` ascending, `?sort=-name` descending; anything else = the API's natural order
 *  (critical devices first, see db.list_systems). */
export function parseSort(value: string): Sort | null {
  const desc = value.startsWith("-");
  const key = (desc ? value.slice(1) : value) as SortKey;
  return SORT_KEYS.includes(key) ? { key, dir: desc ? "desc" : "asc" } : null;
}

/** Header click cycle: ascending -> descending -> unsorted (shared by both list views). */
export function nextSort(sort: Sort | null, key: SortKey): Sort | null {
  if (!sort || sort.key !== key) return { key, dir: "asc" };
  return sort.dir === "asc" ? { key, dir: "desc" } : null;
}

export function formatSort(sort: Sort | null): string {
  if (!sort) return "";
  return sort.dir === "desc" ? `-${sort.key}` : sort.key;
}

const STATUS_ORDER: Record<string, number> = { online: 0, unknown: 1, offline: 2 };

// Pads each octet so string comparison of the result orders IPv4 addresses numerically
// (plain string comparison would put "10" before "2"). Falls back to the raw value for
// anything that isn't a dotted-quad, which still sorts consistently even if not numerically.
function ipSortKey(ip: string): string {
  const parts = ip.split(".");
  if (parts.length !== 4 || !parts.every((p) => /^\d{1,3}$/.test(p))) return ip;
  return parts.map((p) => p.padStart(3, "0")).join(".");
}

export const projectOf = (s: System): string => {
  const docker = (s.extra as { docker?: { composeProject?: string } } | undefined)?.docker;
  return docker?.composeProject ?? "";
};

export interface InventoryFilter {
  q: string;
  kind: string;
  project: string;
  parentId: string;
  status: string;
  importance: string;
  /** CIDR such as `192.168.20.0/24`, or `none` for devices without a usable IPv4 address. */
  subnet: string;
}

export const NO_SUBNET = "none";

export interface ParsedNetwork { base: number; prefix: number; cidr: string; name: string }

function ipv4ToInt(ip: string): number | null {
  const parts = ip.trim().split(".");
  if (parts.length !== 4 || !parts.every((p) => /^\d{1,3}$/.test(p) && Number(p) <= 255)) return null;
  return parts.reduce((acc, p) => acc * 256 + Number(p), 0) >>> 0;
}

const intToIpv4 = (n: number): string => [24, 16, 8, 0].map((sh) => (n >>> sh) & 255).join(".");
const maskOf = (prefix: number): number => (prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0);

/** Parses UniFi network facts (`facts.cidr`); invalid values and IPv6 are dropped. */
export function parseNetworks(resources: { name: string; facts: Record<string, any> }[]): ParsedNetwork[] {
  const out: ParsedNetwork[] = [];
  for (const r of resources) {
    const raw = typeof r.facts?.cidr === "string" ? r.facts.cidr.trim() : "";
    const m = /^([\d.]+)\/(\d{1,2})$/.exec(raw);
    if (!m) continue;
    const addr = ipv4ToInt(m[1]);
    const prefix = Number(m[2]);
    if (addr === null || prefix > 32) continue;
    const base = (addr & maskOf(prefix)) >>> 0;
    out.push({ base, prefix, cidr: `${intToIpv4(base)}/${prefix}`, name: (r.name ?? "").trim() });
  }
  return out;
}

/** Subnet of an IP: the narrowest matching UniFi network, else its /24; no valid IPv4 = `none`. */
export function subnetOf(ip: string, networks: ParsedNetwork[]): { key: string; base: number; prefix: number; name: string } {
  const n = ipv4ToInt(ip || "");
  if (n === null) return { key: NO_SUBNET, base: Infinity, prefix: 0, name: "" };
  let best: ParsedNetwork | null = null;
  for (const net of networks) {
    if (((n & maskOf(net.prefix)) >>> 0) === net.base && (!best || net.prefix > best.prefix)) best = net;
  }
  if (best) return { key: best.cidr, base: best.base, prefix: best.prefix, name: best.name };
  const base = (n & maskOf(24)) >>> 0;
  return { key: `${intToIpv4(base)}/24`, base, prefix: 24, name: "" };
}

/** Occupied subnets (whole inventory) for the filter dropdown, ordered by network address. */
export function subnetOptions(systems: System[], networks: ParsedNetwork[]): { value: string; label: string; count: number }[] {
  const map = new Map<string, { base: number; prefix: number; name: string; count: number }>();
  for (const s of systems) {
    const sub = subnetOf(s.ip, networks);
    const cur = map.get(sub.key);
    if (cur) cur.count += 1; else map.set(sub.key, { base: sub.base, prefix: sub.prefix, name: sub.name, count: 1 });
  }
  return [...map.entries()]
    .sort((a, b) => (a[1].base - b[1].base) || (a[1].prefix - b[1].prefix) || 0)
    .map(([value, v]) => ({
      value,
      label: value === NO_SUBNET ? "ohne Adresse" : v.name ? `${v.name} (${value})` : value,
      count: v.count,
    }));
}

export function readFilter(params: URLSearchParams): InventoryFilter {
  return {
    q: params.get("q") ?? "",
    kind: params.get("kind") ?? "",
    project: params.get("project") ?? "",
    parentId: params.get("parentId") ?? "",
    status: params.get("status") ?? "",
    importance: params.get("importance") ?? "",
    subnet: params.get("subnet") ?? "",
  };
}

export function matchesFilter(s: System, f: InventoryFilter & { networks?: ParsedNetwork[] }): boolean {
  if (f.kind && s.kind !== f.kind) return false;
  if (f.parentId && s.parentId !== f.parentId) return false;
  if (f.project && projectOf(s) !== f.project) return false;
  if (f.status && s.status !== f.status) return false;
  if (f.importance && s.importance !== f.importance) return false;
  if (f.subnet && subnetOf(s.ip, f.networks ?? []).key !== f.subnet) return false;
  return matchesDeviceQuery(s, f.q);
}

export function sortSystems(list: System[], sort: Sort | null, kindLabels: Record<string, string>): System[] {
  if (!sort) return list; // natural order -- critical devices already first, see list_systems
  const sign = sort.dir === "asc" ? 1 : -1;
  const value = (s: System): string | number => {
    switch (sort.key) {
      case "ip": return ipSortKey(s.ip || "");
      case "kind": return kindLabels[s.kind] ?? s.kind;
      case "location": return s.location || "";
      case "status": return STATUS_ORDER[s.status] ?? 1;
      default: return s.name.toLowerCase();
    }
  };
  return [...list].sort((a, b) => {
    const va = value(a), vb = value(b);
    return va < vb ? -sign : va > vb ? sign : 0;
  });
}

/** Devices without a compose project keep their order and get no header; each project becomes one
 *  collapsible group (alphabetical), sorting and search apply within the groups. */
export function groupByProject(visible: System[]): { loose: System[]; stacks: { name: string; items: System[] }[] } {
  const byProject = new Map<string, System[]>();
  const loose: System[] = [];
  for (const s of visible) {
    const p = projectOf(s);
    if (!p) { loose.push(s); continue; }
    byProject.set(p, [...(byProject.get(p) ?? []), s]);
  }
  const names = [...byProject.keys()].sort((a, b) => a.localeCompare(b));
  return { loose, stacks: names.map((name) => ({ name, items: byProject.get(name)! })) };
}
