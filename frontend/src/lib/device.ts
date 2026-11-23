import { api, type Account, type ConfigVersion, type RemoteContainer, type System } from "./api";

/**
 * Device-page helpers shared by the device page and its tabs
 * (pages/device/DevicePage.tsx), so both decide "which account can reboot / open a console" the
 * same way. Pure functions over what `GET /api/systems/{id}` already returns.
 */

/** Same eligibility test as the backend's `_ssh_eligible` / probe_auth's SSH branch -- keep these in sync. */
export function sshEligible(a: Account): boolean {
  const port = a.port || 0;
  return a.category === "sshkey" || (a.category === "login" && (port === 0 || port === 22));
}

export const KINDS = [
  "router", "network", "server", "nas", "container", "vm", "pc", "mobile", "printer",
  "camera", "smarthome", "climate", "heating", "energy", "media", "iot", "other",
];

/** SSH console/remote-container actions require an account directly attached via systemId -- the
 *  backend's _remote_host_and_account/_proxmox_account only ever look at that field, so a
 *  group-assigned account (viaAssignment) is shown but can't drive them. */
export function directAccounts(accounts: Account[]): Account[] {
  return accounts.filter((a) => !a.viaAssignment);
}

/** Same is_fritzbox heuristic as the backend's own POST /systems/{id}/reboot -- a router almost
 *  never runs SSH, and a Linux host almost never speaks TR-064, so exactly one of these two
 *  credential shapes applies to a given device, never both. */
export function rebootAccountFor(system: System, accounts: Account[]): Account | undefined {
  const direct = directAccounts(accounts);
  const looksLikeFritzbox = [system.vendor, system.model, system.name].join(" ").toLowerCase().includes("fritz");
  return looksLikeFritzbox
    ? direct.find((a) => a.category === "login")
    : direct.find(sshEligible);
}

export function isShelly(system: System): boolean {
  return [system.vendor, system.model].join(" ").toLowerCase().includes("shelly");
}

export function hasConfigHistory(system: System): boolean {
  return system.kind === "router" || system.kind === "network";
}

/** Native Proxmox noVNC console URL for one guest -- opened in a new tab rather than proxied
 *  through HomeAtlas: Proxmox already has its own authenticated console. Requires `node` (only
 *  known for guests the REST listing itself returned). */
export function proxmoxConsoleUrl(baseUrl: string, node: string, kind: RemoteContainer["kind"], vmid: string, name: string): string {
  const params = new URLSearchParams({
    console: kind === "vm" ? "kvm" : "lxc", novnc: "1", vmid, vmname: name, node, resize: "off", cmd: "",
  });
  return `${baseUrl}/?${params.toString()}`;
}

/** Downloads one stored config backup. Binary backups (e.g. an Omada Controller export) are stored
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

/** Reads a streamed container log into `onText` (bounded to the last 20 000 characters, so a live
 *  tail left open for hours can't grow the tab's memory without limit). Ends when `signal` aborts. */
export async function streamContainerLogs(systemId: string, signal: AbortSignal, onText: (update: (current: string) => string) => void) {
  try {
    const response = await fetch(api.containerLogsUrl(systemId), { credentials: "same-origin", signal });
    const reader = response.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      onText((current) => (current + decoder.decode(value, { stream: true })).slice(-20000));
    }
  } catch {
    /* aborted, or the connection dropped -- either way nothing to report */
  }
}
