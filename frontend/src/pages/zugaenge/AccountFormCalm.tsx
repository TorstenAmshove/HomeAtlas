import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, type Account, type AccountAssignment, type System } from "../../lib/api";
import ConfirmDialog from "../../components/ConfirmDialog";
import { Skeleton, SkeletonText } from "../../components/Skeleton";
import { useLeaveGuard } from "../../lib/useLeaveGuard";
import { usePageTitle } from "../../shell/pageTitle";
import { CATEGORIES } from "./categories";
import {
  NEW_ACCOUNT, clearAccountDraft, emptyForm, formOfAccount, readAccountDraft, sameForm, setAccountsFlash,
  storeAccountDraft, type AccountForm,
} from "./accountDraft";
import DeleteAccountDialog from "./DeleteAccountDialog";
import "../mehr/mehr.css";

/**
 * "Neuer Zugang" (`/zugaenge/neu`) and "Zugang bearbeiten" (`/zugaenge/:id`) in the new UI, as their
 * own routes instead of a form that replaced the list in page state (forensics "Zugänge" 3).
 *
 * The form keeps a draft in sessionStorage (accountDraft.ts) and asks before leaving with unsaved
 * changes (lib/useLeaveGuard.tsx). The secret fields are the exception on purpose: they live only in
 * this component's state and are never written to storage or the URL; after a reload the form says
 * that the password has to be entered again. Same requests as the classic form.
 */

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

function secretLabel(category: string): string {
  return category === "snmp" ? "Community-Zeichenkette"
    : category === "omada" ? "Client Secret"
    : category === "homeassistant" ? "Zugriffstoken (Long-Lived Access Token)"
    : category === "proxmox" ? "Token-Secret (UUID)"
    : "Passwort";
}

function keepHint(category: string): string {
  return `Leer lassen, um ${category === "snmp" ? "die gespeicherte Community-Zeichenkette"
    : category === "omada" ? "das gespeicherte Client Secret"
    : category === "homeassistant" ? "das gespeicherte Zugriffstoken"
    : category === "proxmox" ? "das gespeicherte Token-Secret"
    : "das gespeicherte Passwort"} beizubehalten.`;
}

export default function AccountFormCalm({ mode }: { mode: "new" | "edit" }) {
  const params = useParams();
  const id = mode === "edit" ? params.id ?? "" : "";
  const draftId = mode === "edit" ? id : NEW_ACCOUNT;
  const navigate = useNavigate();
  const location = useLocation();

  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [systems, setSystems] = useState<System[]>([]);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState<AccountForm | null>(null);
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [restored, setRestored] = useState<{ secretTyped: boolean } | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [keyBusy, setKeyBusy] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [deleting, setDeleting] = useState<Account | null>(null);

  const [assignments, setAssignments] = useState<AccountAssignment[]>([]);
  const [assignType, setAssignType] = useState<"kind" | "subnet" | "system">("kind");
  const [assignValue, setAssignValue] = useState("");
  const [assignBusy, setAssignBusy] = useState(false);

  const publicKey = (location.state as { publicKey?: string } | null)?.publicKey ?? "";

  useEffect(() => {
    setAccounts(null);
    setForm(null);
    setSecret("");
    setPassphrase("");
    setRestored(null);
    Promise.all([api.listAccounts(), api.listSystems()])
      .then(([a, s]) => {
        setAccounts(a.accounts);
        setSystems(s.systems);
        setKindLabels(s.kindLabels);
      })
      .catch((e) => setLoadError(errorText(e)));
    if (mode === "edit" && id) {
      api.listAccountAssignments(id).then((r) => setAssignments(r.assignments)).catch(() => setAssignments([]));
    }
  }, [mode, id]);

  const account = mode === "edit" ? accounts?.find((a) => a.id === id) ?? null : null;
  const base = useMemo(() => (account ? formOfAccount(account) : emptyForm()), [account]);

  // Build the form once the data is there: from the stored draft if there is one.
  useEffect(() => {
    if (accounts === null || form !== null) return;
    if (mode === "edit" && !account) return;
    const draft = readAccountDraft(draftId);
    if (draft) {
      const { secretTyped, ...fields } = draft;
      setForm(fields);
      if (!sameForm(fields, base) || secretTyped) setRestored({ secretTyped });
    } else {
      setForm(base);
    }
  }, [accounts, account, base, draftId, form, mode]);

  usePageTitle(mode === "new" ? "Neuer Zugang" : account?.label ?? null);

  const secretTyped = secret !== "" || passphrase !== "";
  const dirty = form !== null && (!sameForm(form, base) || secretTyped);
  const [leaveDialog] = useLeaveGuard(dirty, mode === "new" ? "dem neuen Zugang" : `„${account?.label ?? "Zugang"}“`);

  const systemName = useMemo(
    () => Object.fromEntries(systems.map((s) => [s.id, s.name])) as Record<string, string>,
    [systems],
  );

  function update(patch: Partial<AccountForm>) {
    if (!form) return;
    const next = { ...form, ...patch };
    setForm(next);
    storeAccountDraft(draftId, next, base, secretTyped);
  }

  function updateSecret(value: string, which: "secret" | "passphrase") {
    if (which === "secret") setSecret(value);
    else setPassphrase(value);
    const typed = (which === "secret" ? value : secret) !== "" || (which === "passphrase" ? value : passphrase) !== "";
    // Only the fact that something was typed is stored, never the value.
    if (form) storeAccountDraft(draftId, form, base, typed);
  }

  function goBack() {
    if (location.key !== "default") navigate(-1);
    else navigate("/zugaenge", { replace: true });
  }

  function discard() {
    clearAccountDraft(draftId);
    setSecret("");
    setPassphrase("");
    setForm(base);
    setDiscardOpen(false);
    goBack();
  }

  async function save() {
    if (!form || !form.label.trim()) return;
    setSaving(true);
    setError("");
    try {
      const body = {
        systemId: form.systemId || null,
        label: form.label.trim(),
        category: form.category,
        username: form.username,
        secret,
        passphrase,
        url: form.url,
        notes: form.notes,
        allowProbe: form.allowProbe,
        port: Number(form.port) || 0,
      };
      if (mode === "edit") await api.updateAccount(id, body);
      else await api.createAccount(body);
      clearAccountDraft(draftId);
      setSecret("");
      setPassphrase("");
      setForm(null);
      setAccountsFlash(mode === "edit" ? `Zugang „${body.label}“ gespeichert.` : `Zugang „${body.label}“ angelegt.`);
      goBack();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function generateKey() {
    if (!form || !form.systemId) return;
    setKeyBusy(true);
    setError("");
    try {
      const r = await api.generateSshKey(form.systemId, form.label.trim() || "SSH-Schlüssel (HomeAtlas)");
      clearAccountDraft(draftId);
      setForm(null);
      // The new key is stored right away; continue on its own page (the public half is not secret).
      navigate(`/zugaenge/${r.account.id}`, { replace: true, state: { publicKey: r.publicKey } });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setKeyBusy(false);
    }
  }

  async function writeAssignments(next: { targetType: string; targetValue: string }[]) {
    setAssignBusy(true);
    setError("");
    try {
      const r = await api.setAccountAssignments(id, next);
      setAssignments(r.assignments);
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setAssignBusy(false);
    }
  }

  async function addAssignment() {
    if (!assignValue.trim()) return;
    const ok = await writeAssignments([
      ...assignments.map((a) => ({ targetType: a.targetType, targetValue: a.targetValue })),
      { targetType: assignType, targetValue: assignValue.trim() },
    ]);
    if (ok) setAssignValue("");
  }

  async function removeAssignment(assignment: AccountAssignment) {
    await writeAssignments(assignments.filter((a) => a.id !== assignment.id)
      .map((a) => ({ targetType: a.targetType, targetValue: a.targetValue })));
  }

  if (loadError) {
    return (
      <div className="mehr-calm zugaenge-calm">
        <div className="notice error" role="alert">{loadError}</div>
        <Link className="m-link" to="/zugaenge">Zur Liste der Zugänge</Link>
      </div>
    );
  }
  if (accounts !== null && mode === "edit" && !account) {
    return (
      <div className="mehr-calm zugaenge-calm">
        <div className="m-empty">
          <h2>Diesen Zugang gibt es nicht (mehr)</h2>
          <p>Vielleicht wurde er gelöscht oder der Link ist unvollständig.</p>
          <Link className="m-btn" to="/zugaenge">Zur Liste der Zugänge</Link>
        </div>
      </div>
    );
  }
  if (!form) {
    return (
      <div className="mehr-calm zugaenge-calm m-form" role="status" aria-live="polite">
        <span className="visually-hidden">Wird geladen …</span>
        <div className="grid cols-2">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="field"><Skeleton width={120} height={12} /><Skeleton height={40} radius={8} style={{ marginTop: 6 }} /></div>
          ))}
        </div>
        <SkeletonText lines={2} />
      </div>
    );
  }

  const isNew = mode === "new";
  const editingSecret = !isNew && Boolean(account?.hasSecret);

  return (
    <div className="mehr-calm zugaenge-calm">
      {leaveDialog}
      <h1 className="visually-hidden">{isNew ? "Neuer Zugang" : `Zugang „${account?.label}“ bearbeiten`}</h1>

      <ConfirmDialog
        open={discardOpen}
        title="Änderungen verwerfen?"
        consequences={[<>Deine ungespeicherten Änderungen {isNew ? "am neuen Zugang" : `an „${account?.label}“`} gehen verloren.</>]}
        confirmLabel="Verwerfen"
        cancelLabel="Weiter bearbeiten"
        danger
        onCancel={() => setDiscardOpen(false)}
        onConfirm={discard}
      />
      <DeleteAccountDialog
        account={deleting}
        systemName={systemName}
        kindLabels={kindLabels}
        onCancel={() => setDeleting(null)}
        onDeleted={(deleted) => {
          setDeleting(null);
          clearAccountDraft(draftId);
          setSecret("");
          setPassphrase("");
          setForm(null);
          setAccountsFlash(`Zugang „${deleted.label}“ gelöscht.`);
          navigate("/zugaenge", { replace: true });
        }}
      />

      {publicKey && (
        <div className="notice ok" role="status">
          Schlüssel erzeugt und gespeichert. Öffentlicher Teil (für <span className="mono">authorized_keys</span> auf dem Gerät):
          <code className="mono m-secret-value" style={{ display: "block", marginTop: 6 }}>{publicKey}</code>
        </div>
      )}
      {restored && (
        <div className="m-note" role="status">
          Ungespeicherte Änderungen aus diesem Browser-Tab wiederhergestellt.
          {restored.secretTyped && (
            <> {secretLabel(form.category)} und Passphrase werden aus Sicherheitsgründen nie zwischengespeichert; bitte noch einmal eingeben.</>
          )}
        </div>
      )}
      {error && <div className="notice error" role="alert">{error}</div>}

      <form className="m-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <div className="grid cols-2">
          <div className="field">
            <label htmlFor="zg-label">Bezeichnung</label>
            <input id="zg-label" autoFocus={isNew} placeholder="z. B. Telekom Kundenkonto" value={form.label}
                   onChange={(e) => update({ label: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="zg-category">Art</label>
            <select id="zg-category" value={form.category} onChange={(e) => update({ category: e.target.value })}>
              {CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="zg-system">Gehört zu welchem Gerät?</label>
            <select id="zg-system" value={form.systemId} onChange={(e) => update({ systemId: e.target.value })}>
              <option value="">— zu keinem bestimmten Gerät —</option>
              {systems.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <div className="field-hint">Verträge und Online-Konten brauchen das nicht.</div>
          </div>
          <div className="field">
            <label htmlFor="zg-username">
              {form.category === "omada" ? "Client-ID"
                : form.category === "proxmox" ? "Token-ID (z. B. root@pam!homeatlas)"
                : "Benutzername / Kundennummer"}
            </label>
            <input id="zg-username" value={form.username} autoComplete="off"
                   onChange={(e) => update({ username: e.target.value })} />
          </div>

          {form.category === "sshkey" ? (
            <>
              {isNew && (
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <button className="m-btn" type="button" onClick={() => void generateKey()} disabled={keyBusy || !form.systemId}>
                    {keyBusy ? "Erzeuge …" : "Neuen Schlüssel erzeugen"}
                  </button>
                  <div className="field-hint">
                    Erzeugt ein Ed25519-Schlüsselpaar für das oben gewählte Gerät und speichert es direkt;
                    ersetzt die Eingabe unten. Braucht ein gewähltes Gerät.
                  </div>
                </div>
              )}
              <div className="field" style={{ gridColumn: "1 / -1" }}>
                <label htmlFor="zg-secret">Privater SSH-Schlüssel (von Hand eintragen, falls schon vorhanden)</label>
                <textarea id="zg-secret" data-secret="true" style={{ minHeight: 150 }} spellCheck={false} autoComplete="off"
                          value={secret}
                          placeholder={editingSecret ? "unverändert lassen" : "-----BEGIN OPENSSH PRIVATE KEY-----\n…\n-----END OPENSSH PRIVATE KEY-----"}
                          onChange={(e) => updateSecret(e.target.value, "secret")} />
                <div className="field-hint">
                  Der <strong>private</strong> Schlüssel, vollständig mit BEGIN- und END-Zeile. Wird verschlüsselt
                  gespeichert und nie zwischengespeichert.
                </div>
              </div>
              <div className="field">
                <label htmlFor="zg-passphrase">Passphrase des Schlüssels (falls vorhanden)</label>
                <input id="zg-passphrase" data-secret="true" type="password" autoComplete="new-password" value={passphrase}
                       placeholder={!isNew && account?.hasPassphrase ? "unverändert lassen" : ""}
                       onChange={(e) => updateSecret(e.target.value, "passphrase")} />
              </div>
            </>
          ) : (
            <div className="field">
              <label htmlFor="zg-secret">{secretLabel(form.category)}</label>
              <input id="zg-secret" data-secret="true" type="password" autoComplete="new-password" value={secret}
                     placeholder={editingSecret ? "unverändert lassen" : ""}
                     onChange={(e) => updateSecret(e.target.value, "secret")} />
              <div className="field-hint">
                {editingSecret
                  ? keepHint(form.category)
                  : form.category === "homeassistant"
                    ? "Wird verschlüsselt gespeichert. Erzeugt im Profil des HA-Benutzers unter „Long-Lived Access Tokens“."
                    : form.category === "proxmox"
                      ? "Wird verschlüsselt gespeichert. Erzeugt unter Datacenter → Berechtigungen → API-Tokens."
                      : "Wird verschlüsselt gespeichert."}
              </div>
            </div>
          )}

          <div className="field">
            <label htmlFor="zg-url">
              Adresse{["omada", "homeassistant", "proxmox", "adguard"].includes(form.category) ? "" : " (optional)"}
            </label>
            <input id="zg-url" placeholder="https://…" value={form.url} onChange={(e) => update({ url: e.target.value })} />
            {form.category === "omada" && (
              <div className="field-hint">
                Basis-Adresse des Controllers, z. B. https://192.168.1.10:8043. Client-ID und Client Secret
                werden unter Einstellungen → Plattform-Integration → Open API im Controller selbst angelegt.
              </div>
            )}
            {form.category === "proxmox" && (
              <div className="field-hint">
                Basis-Adresse des Proxmox-Hosts, z. B. https://192.168.1.20:8006. Dieser Zugang sollte am
                Proxmox-Host selbst (als „Gehört zu welchem Gerät?“) hängen, damit gefundene VMs/Container dort
                eingeordnet werden.
              </div>
            )}
            {form.category === "homeassistant" && (
              <div className="field-hint">Basis-Adresse von Home Assistant, z. B. http://192.168.1.5:8123.</div>
            )}
            {form.category === "adguard" && (
              <div className="field-hint">
                Basis-Adresse von AdGuard Home, z. B. http://192.168.1.2:3000. Benutzername und Passwort sind
                die des AdGuard-Administrators (dieselben wie für die Weboberfläche).
              </div>
            )}
          </div>
          {(form.category === "sshkey" || form.category === "login" || form.category === "snmp") && (
            <div className="field">
              <label htmlFor="zg-port">Abweichender Port (optional)</label>
              <input id="zg-port" type="number" min={0} max={65535} value={form.port || ""}
                     placeholder={form.category === "snmp" ? "Standard (SNMP: 161)" : "Standard (SSH: 22)"}
                     onChange={(e) => update({ port: Number(e.target.value) })} />
            </div>
          )}
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label htmlFor="zg-notes">Notiz (optional)</label>
            <input id="zg-notes" placeholder="z. B. Hotline 0800 …, Vertrag läuft bis …" value={form.notes}
                   onChange={(e) => update({ notes: e.target.value })} />
          </div>
        </div>

        <label className="m-check">
          <input type="checkbox" checked={form.allowProbe} onChange={(e) => update({ allowProbe: e.target.checked })} />
          Diesen Zugang zum Auslesen des Geräts verwenden
        </label>
        <p className="m-hint">
          HomeAtlas meldet sich damit am Gerät an und liest Eckdaten aus: Betriebssystem, Laufzeit,
          Speicherplatz, laufende Container, bei Netzwerkgeräten auch VLANs und Nachbargeräte per LLDP. Es
          werden <strong>ausschließlich</strong> fest einprogrammierte Lesebefehle ausgeführt; nichts wird
          geändert, installiert oder neu gestartet. Ohne diesen Haken bleibt der Zugang reine Ablage.
        </p>

        <h2 className="m-sec">Gilt zusätzlich für</h2>
        {isNew ? (
          <p className="m-hint">Zuordnungen zu weiteren Geräten, Gerätekategorien oder Subnetzen gibt es nach dem ersten Speichern.</p>
        ) : (
          <>
            <p className="m-hint">
              Über „Gehört zu welchem Gerät?“ hinaus kann ein Zugang für eine ganze Gerätekategorie, ein
              Subnetz oder weitere Geräte gelten; der nächste Scan verwendet ihn dort mit (sofern „zum
              Auslesen verwenden“ gesetzt ist). Zuordnungen gelten sofort, ohne „Speichern“.
            </p>
            {assignments.length > 0 && (
              <ul className="m-rows" style={{ marginBottom: 8 }}>
                {assignments.map((a) => (
                  <li key={a.id} className="m-row" style={{ minHeight: 48 }}>
                    <span className="m-row-main">
                      {a.targetType === "kind" ? `Gerätekategorie: ${kindLabels[a.targetValue] ?? a.targetValue}`
                        : a.targetType === "subnet" ? `Subnetz: ${a.targetValue}`
                        : `Gerät: ${systemName[a.targetValue] ?? a.targetValue}`}
                    </span>
                    <button type="button" className="m-btn small" disabled={assignBusy} onClick={() => void removeAssignment(a)}>
                      Entfernen
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="m-inline-form">
              <select aria-label="Art der Zuordnung" value={assignType}
                      onChange={(e) => { setAssignType(e.target.value as typeof assignType); setAssignValue(""); }}>
                <option value="kind">Gerätekategorie</option>
                <option value="subnet">Subnetz</option>
                <option value="system">Weiteres Gerät</option>
              </select>
              {assignType === "kind" ? (
                <select aria-label="Gerätekategorie" value={assignValue} onChange={(e) => setAssignValue(e.target.value)}>
                  <option value="">— wählen —</option>
                  {Object.entries(kindLabels).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}
                </select>
              ) : assignType === "subnet" ? (
                <input aria-label="Subnetz" placeholder="z. B. 192.168.2.0/24" value={assignValue}
                       onChange={(e) => setAssignValue(e.target.value)} />
              ) : (
                <select aria-label="Gerät" value={assignValue} onChange={(e) => setAssignValue(e.target.value)}>
                  <option value="">— Gerät wählen —</option>
                  {systems.filter((s) => s.id !== form.systemId).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              )}
              <button type="button" className="m-btn" disabled={assignBusy || !assignValue.trim()} onClick={() => void addAssignment()}>
                Hinzufügen
              </button>
            </div>
          </>
        )}

        <div className="m-form-foot">
          <button type="submit" className="m-btn primary" disabled={saving || !form.label.trim()}>
            {saving ? "Speichere …" : isNew ? "Zugang anlegen" : "Speichern"}
          </button>
          <button type="button" className="m-btn" onClick={() => (dirty ? setDiscardOpen(true) : goBack())}>
            Abbrechen
          </button>
          {!isNew && account && (
            <button type="button" className="m-btn" style={{ marginLeft: "auto", color: "var(--c-bad)" }}
                    onClick={() => setDeleting(account)}>
              Löschen …
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
