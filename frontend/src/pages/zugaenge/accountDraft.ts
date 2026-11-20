import type { Account } from "../../lib/api";
import { readDraft, writeDraft } from "../../lib/drafts";

/**
 * Unsaved "Zugang" form, kept in sessionStorage (forensics "Zugänge" 3: Back used to throw the form
 * away). Same prefix as lib/drafts.ts, so logout's `clearAllDrafts()` removes it too.
 *
 * The secret fields (password/token/private key and the key passphrase) are deliberately NOT part
 * of this type and are never written: a draft in storage must not become a second, unencrypted copy
 * of a credential (README "Sicherheit"). Only the fact that something was typed there is kept
 * (`secretTyped`), so the form can say "please enter the password again" after a reload.
 */

export interface AccountForm {
  systemId: string;
  label: string;
  category: string;
  username: string;
  url: string;
  notes: string;
  allowProbe: boolean;
  port: number;
}

export interface StoredAccountDraft extends AccountForm {
  secretTyped: boolean;
}

/** Fields that go into storage, in one place, so a new secret field can't slip in by accident. */
const STORED_FIELDS = ["systemId", "label", "category", "username", "url", "notes", "allowProbe", "port"] as const;

export const NEW_ACCOUNT = "neu";
export const accountDraftKey = (id: string) => `account.form.${id}`;

export function emptyForm(systemId = ""): AccountForm {
  return { systemId, label: "", category: "contract", username: "", url: "", notes: "", allowProbe: false, port: 0 };
}

export function formOfAccount(account: Account): AccountForm {
  return {
    systemId: account.systemId ?? "",
    label: account.label,
    category: account.category,
    username: account.username,
    url: account.url,
    notes: account.notes,
    allowProbe: Boolean(account.allowProbe),
    port: account.port ?? 0,
  };
}

export function sameForm(a: AccountForm, b: AccountForm): boolean {
  return STORED_FIELDS.every((field) => (a[field] || "") === (b[field] || ""));
}

export function readAccountDraft(id: string): StoredAccountDraft | null {
  const raw = readDraft(accountDraftKey(id));
  if (raw === null) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object") return null;
    const base = emptyForm();
    const form = { ...base } as Record<string, unknown>;
    for (const field of STORED_FIELDS) {
      if (typeof parsed[field] === typeof base[field]) form[field] = parsed[field];
    }
    return { ...(form as unknown as AccountForm), secretTyped: parsed.secretTyped === true };
  } catch {
    return null;
  }
}

/** Stores the form (never a secret) while it differs from `saved` or a secret was typed. */
export function storeAccountDraft(id: string, form: AccountForm, saved: AccountForm, secretTyped: boolean): void {
  if (sameForm(form, saved) && !secretTyped) {
    writeDraft(accountDraftKey(id), null);
    return;
  }
  const stored: Record<string, unknown> = { secretTyped };
  for (const field of STORED_FIELDS) stored[field] = form[field];
  writeDraft(accountDraftKey(id), JSON.stringify(stored));
}

export function clearAccountDraft(id: string): void {
  writeDraft(accountDraftKey(id), null);
}

/** One-shot message for the list after the form saved and went back (kept in memory only). */
let flash: string | null = null;
export function setAccountsFlash(message: string): void { flash = message; }
export function takeAccountsFlash(): string | null {
  const message = flash;
  flash = null;
  return message;
}
