/** Account categories, shared by the classic page (AccountsPage.tsx) and the new one. */
export const CATEGORIES: [string, string][] = [
  ["contract", "Vertrag / Kundenkonto"],
  ["login", "Anmeldung an Gerät oder Dienst"],
  ["sshkey", "SSH-Schlüssel"],
  ["snmp", "SNMP (Community-Zeichenkette)"],
  ["omada", "Omada Controller (Open API)"],
  ["unifi", "UniFi Network (API-Key)"],
  ["homeassistant", "Home Assistant (Long-Lived Access Token)"],
  ["proxmox", "Proxmox VE (API-Token)"],
  ["adguard", "AdGuard Home (Basic Auth)"],
  ["wifi", "WLAN-Zugang"],
  ["apikey", "API-Schlüssel"],
  ["other", "Sonstiges"],
];

export const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES);
