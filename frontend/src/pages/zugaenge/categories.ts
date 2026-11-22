/** Account categories, shared by the list and the form. */
export const CATEGORIES = [
  ["contract", "Vertrag / Kundenkonto"],
  ["login", "Anmeldung an Gerät oder Dienst"],
  ["sshkey", "SSH-Schlüssel"],
  ["snmp", "SNMP (Community-Zeichenkette)"],
  ["omada", "Omada Controller (Open API)"],
  ["unifi", "UniFi Network (API-Key)"],
  ["homeassistant", "Home Assistant (Long-Lived Access Token)"],
  ["proxmox", "Proxmox VE (API-Token)"],
  ["adguard", "AdGuard Home (Basic Auth)"],
  ["traefik", "Traefik API (Basic Auth)"],
  ["cloudflare", "Cloudflare API (Token, nur lesend)"],
  ["exposure_cloudflared", "cloudflared-Konfiguration lesen (SSH-Forced-Command)"],
  ["exposure_caddy", "Caddyfile lesen (SSH-Forced-Command)"],
  ["exposure_ddclient", "ddclient-Konfiguration lesen (SSH-Forced-Command)"],
  ["firewall_nftables", "nftables-Firewall lesen (SSH-Forced-Command, sudo)"],
  ["wifi", "WLAN-Zugang"],
  ["apikey", "API-Schlüssel"],
  ["other", "Sonstiges"],
] as const;

export type CategoryId = (typeof CATEGORIES)[number][0];

export const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES);
