import { readDraft, writeDraft } from "../lib/drafts";

/**
 * What the first-run wizard asks for, used by `gates/SetupCalm.tsx`, which sends it to `POST /api/setup`.
 */

export interface SystemDraft {
  name: string;
  kind: string;
  ip: string;
  location: string;
  purpose: string;
  url: string;
  username: string;
  password: string;
}

export interface AccountDraft {
  label: string;
  category: string;
  username: string;
  secret: string;
  url: string;
  notes: string;
}

export const KINDS = [
  ["router", "Router / Internetzugang"],
  ["network", "Switch, Access Point, Repeater"],
  ["server", "Server / Kleinrechner"],
  ["nas", "Netzwerkspeicher (NAS)"],
  ["pc", "Computer / Notebook"],
  ["printer", "Drucker"],
  ["smarthome", "Smart-Home-Zentrale"],
  ["heating", "Heizung / Wärmepumpe"],
  ["climate", "Klima / Lüftung"],
  ["energy", "Photovoltaik / Wallbox / Zähler"],
  ["media", "TV / Streaming / Lautsprecher"],
  ["camera", "Kamera"],
  ["other", "Etwas anderes"],
];

export const ACCOUNT_CATEGORIES = [
  ["contract", "Vertrag / Kundenkonto"],
  ["login", "Anmeldung an einem Gerät oder Dienst"],
  ["wifi", "WLAN-Zugang"],
  ["apikey", "API-Schlüssel"],
  ["other", "Sonstiges"],
];

export const emptySystem = (kind = "other"): SystemDraft => ({
  name: "", kind, ip: "", location: "", purpose: "", url: "", username: "", password: "",
});

export const emptyAccount = (): AccountDraft => ({
  label: "", category: "contract", username: "", secret: "", url: "", notes: "",
});

export interface SetupForm {
  homeName: string;
  subnet: string;
  systems: SystemDraft[];
  accounts: AccountDraft[];
}

export const initialSetupForm = (): SetupForm => ({
  homeName: "Mein Zuhause",
  subnet: "",
  systems: [{ ...emptySystem("router"), purpose: "Internetzugang und WLAN" }],
  accounts: [{ ...emptyAccount(), label: "Internetanbieter" }],
});

/** True once anything differs from the pre-filled form (logout then asks before throwing it away). */
export const isSetupDirty = (form: SetupForm) => JSON.stringify(form) !== JSON.stringify(initialSetupForm());

export function setupBody(form: SetupForm) {
  return {
    homeName: form.homeName,
    scanSubnets: form.subnet.trim() ? [form.subnet.trim()] : [],
    systems: form.systems.filter((s) => s.name.trim()),
    accounts: form.accounts.filter((a) => a.label.trim()),
  };
}

// ------------------------------------------------------------------------------------------------
// Draft (redesigned wizard only): the household data survives a reload of this tab, in
// sessionStorage via lib/drafts.ts, so logout clears it like every other draft. Passwords and
// account notes (people put access hints there) are deliberately NOT part of it -- they must never
// sit in browser storage. Instead the draft
// remembers *that* a password had been typed (`hadSecrets`), so the wizard can say after a reload
// that those fields need to be filled in again rather than losing them silently.
// ------------------------------------------------------------------------------------------------

const DRAFT_KEY = "setup.wizard";

export interface SetupDraft {
  step: number;
  form: SetupForm;
  hadSecrets: boolean;
}

export const hasTypedSecrets = (form: SetupForm) =>
  form.systems.some((s) => s.password) || form.accounts.some((a) => a.secret || a.notes);

/** `secretsMissing`: a reload already dropped typed passwords and they are not re-entered yet.
 *  `userId`: the draft belongs to the admin who typed it. If a session expires in this tab and a
 *  different person logs in here, they must not see the previous person's household data. */
export function saveSetupDraft(userId: string, step: number, form: SetupForm, secretsMissing = false): void {
  const hadSecrets = secretsMissing || hasTypedSecrets(form);
  const stored = {
    userId,
    step,
    hadSecrets,
    form: {
      homeName: form.homeName,
      subnet: form.subnet,
      systems: form.systems.map((s) => ({ ...s, password: "" })),
      accounts: form.accounts.map((a) => ({ ...a, secret: "", notes: "" })),
    },
  };
  writeDraft(DRAFT_KEY, JSON.stringify(stored));
}

export function loadSetupDraft(userId: string): SetupDraft | null {
  const raw = readDraft(DRAFT_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<SetupDraft> & { userId?: unknown };
    if (parsed.userId !== userId) {
      // Someone else's (or a pre-userId) draft: never show it, and drop it.
      clearSetupDraft();
      return null;
    }
    const base = initialSetupForm();
    const form = parsed.form;
    if (!form || typeof form !== "object") return null;
    const text = (v: unknown, fallback: string) => (typeof v === "string" ? v : fallback);
    // Field by field with type checks, so a damaged storage value can't crash the wizard later
    // (e.g. `.trim()` on a non-string in setupBody).
    const cleanSystem = (s: unknown): SystemDraft => {
      const src = (s && typeof s === "object" ? s : {}) as Record<string, unknown>;
      const empty = emptySystem();
      return {
        name: text(src.name, ""), kind: text(src.kind, empty.kind), ip: text(src.ip, ""),
        location: text(src.location, ""), purpose: text(src.purpose, ""), url: text(src.url, ""),
        username: text(src.username, ""), password: "",
      };
    };
    const cleanAccount = (a: unknown): AccountDraft => {
      const src = (a && typeof a === "object" ? a : {}) as Record<string, unknown>;
      const empty = emptyAccount();
      return {
        label: text(src.label, ""), category: text(src.category, empty.category), username: text(src.username, ""),
        secret: "", url: text(src.url, ""), notes: "",
      };
    };
    const systems = Array.isArray(form.systems) && form.systems.length
      ? form.systems.map(cleanSystem)
      : base.systems;
    const accounts = Array.isArray(form.accounts) && form.accounts.length
      ? form.accounts.map(cleanAccount)
      : base.accounts;
    const step = typeof parsed.step === "number" && parsed.step >= 0 && parsed.step <= 2 ? Math.floor(parsed.step) : 0;
    return {
      step,
      hadSecrets: parsed.hadSecrets === true,
      form: { homeName: text(form.homeName, base.homeName), subnet: text(form.subnet, ""), systems, accounts },
    };
  } catch {
    return null;
  }
}

export function clearSetupDraft(): void {
  writeDraft(DRAFT_KEY, null);
}
