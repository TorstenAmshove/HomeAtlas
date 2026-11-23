import type { System } from "./api";
import { readDraft, writeDraft } from "./drafts";

/**
 * Unsaved "Gerät bearbeiten" form, kept in sessionStorage (forensics "Gerät" 3: Back used to throw
 * the form away). Used by both device pages, so the fix holds in the old and the new UI.
 *
 * Only the form's own fields are stored, never the whole row: on save they are laid over the
 * current device, so a scan that changed other fields meanwhile is not overwritten by stale copies.
 * The key lives here rather than in lib/drafts.ts's `draftKeys` to keep this page's change
 * self-contained; it uses the same prefix, so logout's `clearAllDrafts()` removes it too.
 */

export const DEVICE_FORM_FIELDS = [
  "name", "ip", "hostname", "vendor", "model", "location", "url", "docUrl", "docLink", "purpose",
  "kind", "importance", "descriptionMd", "notes", "tags", "monitored", "monitorPorts",
] as const;

export type DeviceForm = Partial<Pick<System, (typeof DEVICE_FORM_FIELDS)[number]>>;

export const deviceFormKey = (id: string) => `device.form.${id}`;

export function formOf(source: Partial<System>): DeviceForm {
  const form: Record<string, unknown> = {};
  for (const field of DEVICE_FORM_FIELDS) form[field] = source[field];
  return form as DeviceForm;
}

/** Only the form fields whose value differs from the saved device (strict compare, so clearing a
 * field still goes through). PATCH then writes nothing a scan changed in the meantime. */
export function changedFields(form: Partial<System>, saved: System): DeviceForm {
  const out: Record<string, unknown> = {};
  for (const field of DEVICE_FORM_FIELDS) {
    if (form[field] === undefined) continue;
    if (JSON.stringify(form[field]) !== JSON.stringify(saved[field])) out[field] = form[field];
  }
  return out as DeviceForm;
}

/** Empty and missing count as the same ("" vs null, [] vs null, 0 vs undefined). */
function normalized(value: unknown): unknown {
  if (value === null || value === undefined || value === "" || value === 0) return null;
  if (Array.isArray(value) && value.length === 0) return null;
  return value;
}

export function sameForm(a: Partial<System>, b: Partial<System>): boolean {
  return DEVICE_FORM_FIELDS.every((field) => JSON.stringify(normalized(a[field])) === JSON.stringify(normalized(b[field])));
}

export function readDeviceDraft(id: string): DeviceForm | null {
  const raw = readDraft(deviceFormKey(id));
  if (raw === null) return null;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? formOf(parsed) : null;
  } catch {
    return null;
  }
}

/** Stores the form while it differs from the saved device; an unchanged form removes the draft. */
export function storeDeviceDraft(id: string, form: Partial<System>, saved: System): void {
  writeDraft(deviceFormKey(id), sameForm(form, saved) ? null : JSON.stringify(formOf(form)));
}

export function clearDeviceDraft(id: string): void {
  writeDraft(deviceFormKey(id), null);
}
