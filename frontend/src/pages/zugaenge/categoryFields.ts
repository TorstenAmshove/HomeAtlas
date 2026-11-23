import type { AccountForm } from "./accountDraft";
import type { CategoryId } from "./categories";

/**
 * Per-category field definition of the account form: which fields are shown, how they are labelled
 * and what goes where. The form (AccountFormPage.tsx) reads only from here.
 *
 * The data model is unchanged and the labels follow what the backend modules actually read
 * (pipeline.py, probe_auth.py, cloudflare_probe.py, exposure_files.py): e.g. for Cloudflare `url`
 * holds the zone id and `username` the account id. `Record<CategoryId, …>` makes `tsc` (npm run
 * build) fail when a category in categories.ts has no definition.
 */

export interface FieldDef {
  visible: boolean;
  required?: boolean;
  label: string;
  placeholder?: string;
  hint?: string;
}

export interface CategoryFields {
  username: FieldDef;
  url: FieldDef;
  secret: FieldDef & { keepLabel: string };
  /** SSH/SNMP port override; `label`/`placeholder` only matter when visible. */
  port: FieldDef;
  /** "Use for probing" checkbox; hidden for pure storage categories. */
  allowProbe: { visible: boolean; hint?: string };
}

const HIDDEN: FieldDef = { visible: false, label: "" };
const SECRET_STORED = "Wird verschlüsselt gespeichert.";

const userUrl = (url: Partial<FieldDef> & { label: string }): Pick<CategoryFields, "username" | "url"> => ({
  username: { visible: true, label: "Benutzername" },
  url: { visible: true, placeholder: "https://…", ...url },
});

const SSH_PORT: FieldDef = { visible: true, label: "Abweichender Port (optional)", placeholder: "Standard (SSH: 22)" };

const exposure = (what: string): CategoryFields => ({
  username: { visible: true, label: "SSH-Benutzer (optional)", placeholder: "Standard: homeatlas",
    hint: `Benutzer auf dem Gerät, dessen SSH-Schlüssel nur ${what} lesen darf (Forced-Command). Gerät oben unter „Gehört zu welchem Gerät?“ wählen.` },
  url: HIDDEN,
  secret: { visible: true, label: "Privater SSH-Schlüssel", keepLabel: "den gespeicherten Schlüssel",
    hint: SECRET_STORED },
  port: SSH_PORT,
  allowProbe: { visible: true },
});

const storage = (secretLabel: string, usernameLabel: string, urlLabel: string): CategoryFields => ({
  username: { visible: true, label: usernameLabel },
  url: { visible: true, label: `${urlLabel} (optional)`, placeholder: "https://…" },
  secret: { visible: true, label: secretLabel, keepLabel: `das gespeicherte ${secretLabel}`, hint: SECRET_STORED },
  port: HIDDEN,
  allowProbe: { visible: false },
});

const password = (hint = SECRET_STORED) =>
  ({ visible: true, label: "Passwort", keepLabel: "das gespeicherte Passwort", hint }) as const;

export const ACCOUNT_FIELDS: Record<CategoryId, CategoryFields> = {
  contract: storage("Passwort", "Benutzername / Kundennummer", "Adresse"),
  login: {
    username: { visible: true, label: "Benutzername",
      hint: "Klassisches ArubaOS-Switch: Das Konto muss direkt mit Manager-Rechten anmelden; ein enable-Passwort wird nicht beantwortet." },
    url: { visible: true, label: "Adresse (optional)", placeholder: "https://… (nur für Web-Anmeldung)" },
    secret: password(),
    port: SSH_PORT,
    allowProbe: { visible: true },
  },
  sshkey: {
    username: { visible: true, label: "Benutzername", hint: "SSH-Benutzer auf dem Gerät." },
    url: HIDDEN,
    // The key textarea and passphrase are rendered specially by the form; label is the textarea's.
    secret: { visible: true, label: "Privater SSH-Schlüssel (von Hand eintragen, falls schon vorhanden)",
      keepLabel: "den gespeicherten Schlüssel",
      hint: "Der private Schlüssel, vollständig mit BEGIN- und END-Zeile. Wird verschlüsselt gespeichert und nie zwischengespeichert." },
    port: SSH_PORT,
    allowProbe: { visible: true },
  },
  snmp: {
    username: HIDDEN,
    url: HIDDEN,
    secret: { visible: true, label: "Community-Zeichenkette", keepLabel: "die gespeicherte Community-Zeichenkette",
      hint: SECRET_STORED },
    port: { visible: true, label: "Abweichender Port (optional)", placeholder: "Standard (SNMP: 161)" },
    allowProbe: { visible: true },
  },
  omada: {
    username: { visible: true, required: true, label: "Client-ID" },
    url: { visible: true, required: true, label: "Adresse", placeholder: "https://192.168.1.10:8043",
      hint: "Basis-Adresse des Controllers. Client-ID und Client Secret werden unter Einstellungen → Plattform-Integration → Open API im Controller selbst angelegt." },
    secret: { visible: true, required: true, label: "Client Secret", keepLabel: "das gespeicherte Client Secret", hint: SECRET_STORED },
    port: HIDDEN,
    allowProbe: { visible: true },
  },
  unifi: {
    username: HIDDEN,
    url: { visible: true, required: true, label: "Adresse", placeholder: "https://192.168.1.1",
      hint: "Basis-Adresse des UniFi-Network-Controllers." },
    secret: { visible: true, required: true, label: "API-Key", keepLabel: "den gespeicherten API-Key",
      hint: "Wird verschlüsselt gespeichert. Der Key hat die Rechte seines Erstellers." },
    port: HIDDEN,
    allowProbe: { visible: true,
      hint: "„Zum Auslesen verwenden“ liest auch Portweiterleitungen und die WAN-Adresse (nur GET)." },
  },
  homeassistant: {
    username: HIDDEN,
    url: { visible: true, required: true, label: "Adresse", placeholder: "http://192.168.1.5:8123",
      hint: "Basis-Adresse von Home Assistant." },
    secret: { visible: true, required: true, label: "Zugriffstoken (Long-Lived Access Token)",
      keepLabel: "das gespeicherte Zugriffstoken",
      hint: "Wird verschlüsselt gespeichert. Erzeugt im Profil des HA-Benutzers unter „Long-Lived Access Tokens“." },
    port: HIDDEN,
    allowProbe: { visible: true },
  },
  proxmox: {
    username: { visible: true, required: true, label: "Token-ID", placeholder: "root@pam!homeatlas" },
    url: { visible: true, required: true, label: "Adresse", placeholder: "https://192.168.1.20:8006",
      hint: "Basis-Adresse des Proxmox-Hosts. Dieser Zugang sollte am Proxmox-Host selbst (als „Gehört zu welchem Gerät?“) hängen, damit gefundene VMs/Container dort eingeordnet werden." },
    secret: { visible: true, required: true, label: "Token-Secret (UUID)", keepLabel: "das gespeicherte Token-Secret",
      hint: "Wird verschlüsselt gespeichert. Erzeugt unter Datacenter → Berechtigungen → API-Tokens." },
    port: HIDDEN,
    allowProbe: { visible: true },
  },
  adguard: {
    ...userUrl({ label: "Adresse", required: true, placeholder: "http://192.168.1.2:3000",
      hint: "Basis-Adresse von AdGuard Home. Benutzername und Passwort sind die des AdGuard-Administrators (dieselben wie für die Weboberfläche)." }),
    secret: password(),
    port: HIDDEN,
    allowProbe: { visible: true },
  },
  traefik: {
    ...userUrl({ label: "Adresse", required: true, placeholder: "https://traefik.lan.example.org",
      hint: "Adresse der Traefik-API. Benutzername und Passwort eines eigenen BasicAuth-Nutzers nur für die API (lesend, nur GET)." }),
    secret: password(),
    port: HIDDEN,
    allowProbe: { visible: true },
  },
  cloudflare: {
    username: { visible: true, label: "Account-ID (optional)", placeholder: "32 Zeichen, 0–9 und a–f",
      hint: "Ohne Account-ID werden Tunnel nicht ausgelesen. Zu finden im Cloudflare-Dashboard rechts in der Übersicht der Domain." },
    url: { visible: true, required: true, label: "Zone-ID", placeholder: "32 Zeichen, 0–9 und a–f",
      hint: "Zu finden im Cloudflare-Dashboard rechts in der Übersicht der Domain." },
    secret: { visible: true, required: true, label: "API-Token", keepLabel: "das gespeicherte API-Token",
      hint: "Wird verschlüsselt gespeichert. Ein Token mit reinen Leserechten (DNS lesen, ggf. Tunnel lesen) genügt." },
    port: HIDDEN,
    allowProbe: { visible: true },
  },
  exposure_cloudflared: exposure("die cloudflared-Konfiguration"),
  exposure_caddy: exposure("das Caddyfile"),
  exposure_ddclient: exposure("die ddclient-Konfiguration"),
  firewall_nftables: exposure("den nftables-Regelsatz (sudo nft -j list ruleset)"),
  wifi: {
    username: { visible: true, label: "Netzwerkname (SSID)" },
    url: HIDDEN,
    secret: { visible: true, label: "WLAN-Passwort", keepLabel: "das gespeicherte WLAN-Passwort", hint: SECRET_STORED },
    port: HIDDEN,
    allowProbe: { visible: false },
  },
  apikey: {
    username: { visible: true, label: "Dienst / Konto (optional)" },
    url: { visible: true, label: "Adresse (optional)", placeholder: "https://…" },
    secret: { visible: true, label: "API-Schlüssel", keepLabel: "den gespeicherten API-Schlüssel", hint: SECRET_STORED },
    port: HIDDEN,
    allowProbe: { visible: false },
  },
  other: storage("Passwort", "Benutzername / Kundennummer", "Adresse"),
};

/** Unknown categories from old data fall back to the generic definition instead of crashing. */
export function fieldsFor(category: string): CategoryFields {
  return (ACCOUNT_FIELDS as Record<string, CategoryFields | undefined>)[category] ?? ACCOUNT_FIELDS.other;
}

/** Categories whose secret is a private key: a single-line input would strip its line breaks. */
export function usesSshKey(category: string): boolean {
  return category === "sshkey" || category.startsWith("exposure_");
}

const CF_ID = /^[0-9a-f]{32}$/;

/** Client-side check before saving; only Cloudflare has a format the backend enforces. Returns an error text or "". */
export function validateAccountForm(form: AccountForm): string {
  if (form.category !== "cloudflare") return "";
  const zone = form.url.trim();
  const account = form.username.trim();
  if (!zone) return "Zone-ID fehlt. Sie besteht aus 32 Zeichen (0–9 und a–f).";
  if (!CF_ID.test(zone)) return "Die Zone-ID ist ungültig: erwartet werden 32 Zeichen, 0–9 und a–f (Kleinbuchstaben).";
  if (account && !CF_ID.test(account)) return "Die Account-ID ist ungültig: erwartet werden 32 Zeichen, 0–9 und a–f (Kleinbuchstaben).";
  return "";
}
