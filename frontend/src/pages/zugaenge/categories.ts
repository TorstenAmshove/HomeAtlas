/** Account categories, shared by the list and the form. */
export const CATEGORIES: [string, string][] = [
  ["contract", "Vertrag / Kundenkonto"],
  ["login", "Anmeldung an Gerät oder Dienst"],
  ["sshkey", "SSH-Schlüssel"],
  ["snmp", "SNMP (Community-Zeichenkette)"],
  ["omada", "Omada Controller (Open API)"],
  ["unifi", "UniFi Network (API-Key)"],
  ["unifi_classic", "UniFi klassische API (Benutzer View Only)"],
  ["homeassistant", "Home Assistant (Long-Lived Access Token)"],
  ["proxmox", "Proxmox VE (API-Token)"],
  ["adguard", "AdGuard Home (Basic Auth)"],
  ["traefik", "Traefik API (Basic Auth)"],
  ["cloudflare", "Cloudflare API (Token, nur lesend)"],
  ["exposure_cloudflared", "cloudflared-Konfiguration lesen (SSH-Forced-Command)"],
  ["exposure_caddy", "Caddyfile lesen (SSH-Forced-Command)"],
  ["exposure_ddclient", "ddclient-Konfiguration lesen (SSH-Forced-Command)"],
  ["wifi", "WLAN-Zugang"],
  ["apikey", "API-Schlüssel"],
  ["other", "Sonstiges"],
];

export const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES);
