import { DEVICE_SEARCH_FIELDS } from "../nav/config";
import type { System } from "./api";

/** Shared by the device list and the ⌘K search, so both always match the same devices. */
export function matchesDeviceQuery(system: System, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return DEVICE_SEARCH_FIELDS.map((field) => system[field] ?? "")
    .join(" ")
    .toLowerCase()
    .includes(needle);
}
