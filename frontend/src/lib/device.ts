import { api, type ConfigVersion, type System } from "./api";

/**
 * Device-page helpers shared by the device page and its tabs
 * (pages/device/DevicePage.tsx). Pure functions over what `GET /api/systems/{id}` already returns.
 */

export const KINDS = [
  "router", "network", "server", "nas", "container", "vm", "pc", "mobile", "printer",
  "camera", "smarthome", "climate", "heating", "energy", "media", "iot", "other",
];

export function hasConfigHistory(system: System): boolean {
  return system.kind === "router" || system.kind === "network";
}

/** Downloads one stored config backup. Binary backups are stored
 *  as one unbroken Base64 string -- everything else is multi-line device config text, which no real
 *  Base64 payload looks like, so this tells the two apart without a dedicated flag. */
export async function downloadConfigVersion(systemId: string, version: ConfigVersion): Promise<void> {
  const full = (await api.getConfigVersion(systemId, version.id)).version;
  const content = full.content ?? "";
  const isBase64 = content.length % 4 === 0 && /^[A-Za-z0-9+/]+=*$/.test(content);
  const blob = isBase64
    ? new Blob([Uint8Array.from(atob(content), (c) => c.charCodeAt(0))], { type: "application/octet-stream" })
    : new Blob([content], { type: "text/plain" });
  const safeName = full.label.replace(/[^\w.-]+/g, "_");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${safeName}.${isBase64 ? "cfg" : "txt"}`;
  a.click();
  URL.revokeObjectURL(url);
}
