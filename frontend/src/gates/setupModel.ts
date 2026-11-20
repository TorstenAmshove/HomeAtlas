import { readDraft, writeDraft } from "../lib/drafts";

/**
 * What the first-run wizard asks for, shared by the classic `pages/SetupPage.tsx` and the
 * redesigned `gates/SetupCalm.tsx` so both send the same body to `POST /api/setup`.
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
// sessionStorage via lib/drafts.ts, so logout clears it like every other draft. Passwords are
// deliberately NOT part of it -- a secret must never sit in browser storage. Instead the draft
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
  form.systems.some((s) => s.password) || form.accounts.some((a) => a.secret);

/** `secretsMissing`: a reload already dropped typed passwords and they are not re-entered yet. */
export function saveSetupDraft(step: number, form: SetupForm, secretsMissing = false): void {
  const hadSecrets = secretsMissing || hasTypedSecrets(form);
  const stored = {
    step,
    hadSecrets,
    form: {
      homeName: form.homeName,
      subnet: form.subnet,
      systems: form.systems.map((s) => ({ ...s, password: "" })),
      accounts: form.accounts.map((a) => ({ ...a, secret: "" })),
    },
  };
  writeDraft(DRAFT_KEY, JSON.stringify(stored));
}

export function loadSetupDraft(): SetupDraft | null {
  const raw = readDraft(DRAFT_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<SetupDraft>;
    const base = initialSetupForm();
    const form = parsed.form;
    if (!form || typeof form !== "object") return null;
    const text = (v: unknown, fallback: string) => (typeof v === "string" ? v : fallback);
    const systems = Array.isArray(form.systems) && form.systems.length
      ? form.systems.map((s) => ({ ...emptySystem(), ...s, password: "" }))
      : base.systems;
    const accounts = Array.isArray(form.accounts) && form.accounts.length
      ? form.accounts.map((a) => ({ ...emptyAccount(), ...a, secret: "" }))
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
