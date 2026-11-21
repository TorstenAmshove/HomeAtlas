import { useEffect, useState } from "react";
import { api, type Role, type User } from "../../lib/api";
import { useAuth } from "../../App";
import ConfirmDialog from "../../components/ConfirmDialog";
import OverflowMenu, { type OverflowItem } from "../../components/OverflowMenu";
import { Skeleton } from "../../components/Skeleton";
import { useUndoToast } from "../../lib/useUndoToast";
import "./mehr.css";

/**
 * "Benutzer" under Mehr in the new UI: a plain list, "Bearbeiten" on the row, and the two
 * consequential actions (Löschen, Zwei-Faktor zurücksetzen) under "⋯", each with a review step that
 * says what happens. The roles explanation sits behind "ⓘ".
 */

const ROLE_LABEL: Record<Role, string> = { ADMIN: "Administrator", MEMBER: "Mitglied" };
const ROLE_HELP: Record<Role, string> = {
  ADMIN: "Sieht und ändert alles, einschließlich gespeicherter Passwörter und Einstellungen.",
  MEMBER: "Liest die Dokumentation und nutzt den KI-Assistenten. Sieht keine Passwörter, ändert nichts.",
};

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState("");
  const [rolesOpen, setRolesOpen] = useState(false);
  const [toast, showToast] = useUndoToast();

  const [creating, setCreating] = useState(false);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("MEMBER");
  const [busy, setBusy] = useState(false);

  const [editing, setEditing] = useState<User | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState<Role>("MEMBER");
  const [editPassword, setEditPassword] = useState("");

  const [deleting, setDeleting] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);

  async function reload() {
    setUsers((await api.listUsers()).users);
  }

  useEffect(() => {
    reload().catch((e) => { setError(errorText(e)); setUsers([]); });
  }, []);

  function resetForm() {
    setCreating(false);
    setUsername("");
    setDisplayName("");
    setPassword("");
    setRole("MEMBER");
  }

  async function create() {
    setBusy(true);
    setError("");
    try {
      await api.createUser({ username: username.trim(), password, role, displayName: displayName.trim() });
      await reload();
      showToast({ message: `Benutzer „${username.trim()}“ angelegt.` });
      resetForm();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  function startEdit(user: User) {
    setError("");
    setCreating(false);
    setEditing(user);
    setEditName(user.displayName);
    setEditRole(user.role);
    setEditPassword("");
  }

  async function saveEdit() {
    if (!editing) return;
    setBusy(true);
    setError("");
    try {
      const body: { displayName?: string; role?: Role; newPassword?: string } = { displayName: editName, role: editRole };
      if (editPassword) body.newPassword = editPassword;
      const r = await api.updateUser(editing.id, body);
      await reload();
      showToast({ message: r.changes.length > 0 ? `„${editing.username}“: ${r.changes.join(", ")}.` : "Es gab nichts zu ändern." });
      setEditing(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function runDelete() {
    if (!deleting) return;
    setDialogBusy(true);
    try {
      await api.deleteUser(deleting.id);
      showToast({ message: `Benutzer „${deleting.username}“ gelöscht.` });
      setDeleting(null);
      await reload();
    } catch (e) {
      setError(errorText(e));
      setDeleting(null);
    } finally {
      setDialogBusy(false);
    }
  }

  async function runResetMfa() {
    if (!resetting) return;
    setDialogBusy(true);
    try {
      await api.resetUserMfa(resetting.id);
      showToast({ message: `Zwei-Faktor-Anmeldung von „${resetting.username}“ zurückgesetzt.` });
      setResetting(null);
      await reload();
    } catch (e) {
      setError(errorText(e));
      setResetting(null);
    } finally {
      setDialogBusy(false);
    }
  }

  if (users === null) {
    return (
      <div className="mehr-page users-page" role="status" aria-live="polite">
        <span className="visually-hidden">Wird geladen …</span>
        <div className="m-toolbar"><Skeleton width={200} /><Skeleton width={150} height={40} radius={8} style={{ marginLeft: "auto" }} /></div>
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="m-skel-row">
            <div style={{ flex: 1, display: "grid", gap: 6 }}><Skeleton width={`${30 + i * 12}%`} /><Skeleton width="25%" height={10} /></div>
            <Skeleton width={90} height={12} />
          </div>
        ))}
      </div>
    );
  }

  const adminCount = users.filter((u) => u.role === "ADMIN").length;

  return (
    <div className="mehr-page users-page">
      {toast}
      <h1 className="visually-hidden">Benutzer</h1>

      <ConfirmDialog
        open={deleting !== null}
        title={`Benutzer „${deleting?.username ?? ""}“ löschen?`}
        danger
        busy={dialogBusy}
        confirmLabel="Benutzer löschen"
        consequences={deleting ? [
          <>„{deleting.displayName || deleting.username}“ kann sich nicht mehr anmelden; offene Sitzungen enden sofort.</>,
          <>Die Einträge im Protokoll bleiben erhalten.</>,
        ] : undefined}
        onCancel={() => setDeleting(null)}
        onConfirm={runDelete}
      >
        <p className="m-dialog-note">
          Das lässt sich nicht rückgängig machen. Soll die Person wieder Zugriff bekommen, musst du sie neu
          anlegen (mit neuem Passwort und neuer Zwei-Faktor-Einrichtung).
        </p>
      </ConfirmDialog>

      <ConfirmDialog
        open={resetting !== null}
        title="Zwei-Faktor-Anmeldung zurücksetzen?"
        busy={dialogBusy}
        confirmLabel="Zurücksetzen"
        consequences={resetting ? [
          <>„{resetting.displayName || resetting.username}“ muss die Authenticator-App beim nächsten Login neu einrichten.</>,
          <>Der bisherige Eintrag in der App funktioniert danach nicht mehr.</>,
          <>Offene Sitzungen dieses Kontos kommen bis dahin nur noch zur Einrichtung, sonst nirgendwohin.</>,
        ] : undefined}
        onCancel={() => setResetting(null)}
        onConfirm={runResetMfa}
      >
        <p className="m-dialog-note">Gedacht für ein verlorenes oder neu eingerichtetes Handy. Der Vorgang wird protokolliert.</p>
      </ConfirmDialog>

      <div className="m-toolbar">
        <p className="m-summary" style={{ margin: 0, flex: "1 1 auto" }}>
          <b>{users.length}</b> {users.length === 1 ? "Benutzer" : "Benutzer"} · davon <b>{adminCount}</b>{" "}
          {adminCount === 1 ? "Administrator" : "Administratoren"} ·{" "}
          <button type="button" className="m-link" aria-expanded={rolesOpen} onClick={() => setRolesOpen((v) => !v)}>
            ⓘ Was die Rollen bedeuten
          </button>
        </p>
        {!creating && (
          <button type="button" className="m-btn primary" onClick={() => { setEditing(null); setCreating(true); }}>
            + Benutzer anlegen
          </button>
        )}
      </div>

      {rolesOpen && (
        <div className="m-note" data-testid="roles-info">
          <p><strong>{ROLE_LABEL.ADMIN}:</strong> {ROLE_HELP.ADMIN}</p>
          <p><strong>{ROLE_LABEL.MEMBER}:</strong> {ROLE_HELP.MEMBER}</p>
          <p className="muted" style={{ margin: 0 }}>
            Ein Mitgliedskonto ist der sinnvolle Zugang für den Rest des Haushalts: die Notfall-Checkliste und
            der Assistent stehen zur Verfügung, das Router-Passwort aber nicht.
          </p>
        </div>
      )}

      {error && <div className="notice error" role="alert">{error}</div>}

      {creating && (
        <form className="m-form" style={{ margin: "8px 0 20px" }} onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <h2 className="m-sec">Neuer Benutzer</h2>
          <div className="grid cols-2">
            <div className="field">
              <label htmlFor="us-username">Benutzername</label>
              <input id="us-username" autoFocus value={username} autoComplete="off" onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="us-display">Anzeigename (optional)</label>
              <input id="us-display" placeholder="z. B. Anna" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="us-password">Passwort</label>
              <input id="us-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
              <div className="field-hint">Mindestens 8 Zeichen.</div>
            </div>
            <div className="field">
              <label htmlFor="us-role">Rolle</label>
              <select id="us-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                <option value="MEMBER">{ROLE_LABEL.MEMBER}</option>
                <option value="ADMIN">{ROLE_LABEL.ADMIN}</option>
              </select>
              <div className="field-hint">{ROLE_HELP[role]}</div>
            </div>
          </div>
          <div className="m-actions">
            <button type="submit" className="m-btn primary" disabled={busy || !username.trim() || password.length < 8}>
              {busy ? "Lege an …" : "Anlegen"}
            </button>
            <button type="button" className="m-btn" onClick={resetForm}>Abbrechen</button>
          </div>
        </form>
      )}

      <ul className="m-rows" aria-label="Benutzer">
        {users.map((u) => {
          const isMe = u.id === me?.id;
          const isLastAdmin = u.role === "ADMIN" && adminCount <= 1;
          const items: OverflowItem[] = [
            ...(u.totpEnabled ? [{ label: "Zwei-Faktor zurücksetzen …", onSelect: () => setResetting(u) }] : []),
            isMe
              ? { label: "Löschen (nicht das eigene Konto)", onSelect: () => {}, disabled: true }
              : isLastAdmin
                ? { label: "Löschen (letzter Administrator)", onSelect: () => {}, disabled: true }
                : { label: "Löschen …", onSelect: () => setDeleting(u), danger: true },
          ];
          return (
            <li key={u.id} className="m-row" data-testid="user-row">
              <div className="m-row-main">
                <span className="m-row-title">
                  <span className="m-row-name">{u.displayName || u.username}</span>
                  {isMe && <span className="m-tag">das bist du</span>}
                </span>
                <span className="m-row-sub">
                  {u.displayName && u.displayName !== u.username && <><span className="mono">{u.username}</span> · </>}
                  {ROLE_LABEL[u.role]} · angelegt {new Date(u.createdAt).toLocaleDateString("de-DE")}
                </span>
              </div>
              <div className="m-row-side">
                {u.totpEnabled
                  ? <span className="m-chip ok"><span className="dot" aria-hidden="true" />Zwei-Faktor aktiv</span>
                  : <span className="m-chip warn" title="Wird beim nächsten Login erzwungen"><span className="dot" aria-hidden="true" />Zwei-Faktor noch nicht eingerichtet</span>}
                <button type="button" className="m-btn small" onClick={() => startEdit(u)}>Bearbeiten</button>
                <OverflowMenu items={items} label={`Weitere Aktionen für ${u.username}`} />
              </div>
              {editing?.id === u.id && (
                <form className="m-row-panel m-form" onSubmit={(e) => { e.preventDefault(); void saveEdit(); }}>
                  <div className="grid cols-2">
                    <div className="field">
                      <label htmlFor="us-edit-name">Anzeigename</label>
                      <input id="us-edit-name" autoFocus value={editName} onChange={(e) => setEditName(e.target.value)} />
                    </div>
                    <div className="field">
                      <label htmlFor="us-edit-role">Rolle</label>
                      <select id="us-edit-role" value={editRole} onChange={(e) => setEditRole(e.target.value as Role)}>
                        <option value="MEMBER">{ROLE_LABEL.MEMBER}</option>
                        <option value="ADMIN">{ROLE_LABEL.ADMIN}</option>
                      </select>
                      <div className="field-hint">{ROLE_HELP[editRole]}</div>
                    </div>
                    <div className="field" style={{ gridColumn: "1 / -1" }}>
                      <label htmlFor="us-edit-password">Neues Passwort setzen (optional)</label>
                      <input id="us-edit-password" type="password" autoComplete="new-password" value={editPassword}
                             placeholder="leer lassen, um es nicht zu ändern" onChange={(e) => setEditPassword(e.target.value)} />
                      <div className="field-hint">
                        Beim Zurücksetzen werden alle offenen Sitzungen dieses Benutzers beendet; er muss sich danach neu anmelden.
                      </div>
                    </div>
                  </div>
                  <div className="m-actions">
                    <button type="submit" className="m-btn primary" disabled={busy}>{busy ? "Speichere …" : "Speichern"}</button>
                    <button type="button" className="m-btn" onClick={() => setEditing(null)}>Abbrechen</button>
                  </div>
                </form>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
