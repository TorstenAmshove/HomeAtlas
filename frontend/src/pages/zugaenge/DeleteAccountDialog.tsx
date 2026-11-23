import { useEffect, useState } from "react";
import { api, type Account, type AccountAssignment } from "../../lib/api";
import ConfirmDialog from "../../components/ConfirmDialog";

/**
 * Review step before deleting a Zugang (forensics "Zugänge" 1, Q4). Says what is lost, in plain
 * words: the stored password, the device it belongs to, every extra assignment (loaded when the
 * dialog opens, from the same admin-only endpoint the form uses), and that there is no undo -- the
 * backend deletes the row (`DELETE /api/accounts/{id}`); there is no archive to restore from.
 */
export default function DeleteAccountDialog({ account, systemName, kindLabels, onCancel, onDeleted }: {
  account: Account | null;
  systemName: Record<string, string>;
  kindLabels: Record<string, string>;
  onCancel: () => void;
  onDeleted: (account: Account) => void;
}) {
  const [assignments, setAssignments] = useState<AccountAssignment[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setAssignments(null);
    setError("");
    if (!account) return;
    let cancelled = false;
    api.listAccountAssignments(account.id)
      .then((r) => { if (!cancelled) setAssignments(r.assignments); })
      .catch(() => { if (!cancelled) setAssignments([]); });
    return () => { cancelled = true; };
  }, [account]);

  async function run() {
    if (!account) return;
    setBusy(true);
    setError("");
    try {
      await api.deleteAccount(account.id);
      onDeleted(account);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!account) return null;
  const device = account.systemId ? systemName[account.systemId] ?? "ein gelöschtes Gerät" : "";
  const targetLabel = (a: AccountAssignment) =>
    a.targetType === "kind" ? `Gerätekategorie: ${kindLabels[a.targetValue] ?? a.targetValue}`
      : a.targetType === "subnet" ? `Subnetz: ${a.targetValue}`
      : `Gerät: ${systemName[a.targetValue] ?? a.targetValue}`;

  const consequences = [
    account.hasSecret
      ? <>Der Zugang „{account.label}“ wird gelöscht, <strong>samt gespeichertem Passwort</strong>. HomeAtlas hat danach keine Kopie mehr davon.</>
      : <>Der Zugang „{account.label}“ wird gelöscht.</>,
    device
      ? <>„{device}“ verliert diesen Zugang{account.allowProbe ? " und wird damit beim Scan nicht mehr ausgelesen" : ""}.</>
      : <>Er gehört zu keinem bestimmten Gerät.</>,
    assignments === null
      ? <>Zuordnungen werden geladen …</>
      : assignments.length === 0
        ? <>Es gibt keine weiteren Zuordnungen.</>
        : <>
            {assignments.length === 1 ? "Diese Zuordnung entfällt" : `Diese ${assignments.length} Zuordnungen entfallen`}:
            <ul className="m-dialog-list" data-testid="delete-assignments">
              {assignments.map((a) => <li key={a.id}>{targetLabel(a)}</li>)}
            </ul>
          </>,
    ...(account.category === "unifi"
      ? [<>Netze und WLANs, die über diesen Zugang kamen, gelten danach als nicht mehr aktuell.</>]
      : []),
    ...(account.category === "sshkey"
      ? [<>Ein auf dem Gerät eingetragener öffentlicher Schlüssel bleibt dort; HomeAtlas entfernt dort nichts.</>]
      : []),
  ];

  return (
    <ConfirmDialog
      open
      title={`„${account.label}“ löschen?`}
      danger
      busy={busy}
      confirmLabel="Zugang endgültig löschen"
      consequences={consequences}
      onCancel={onCancel}
      onConfirm={run}
    >
      {error && <div className="notice error" role="alert">{error}</div>}
      <p className="m-dialog-note">
        Das lässt sich nicht rückgängig machen; es gibt keinen Papierkorb für Zugänge. Wer das Passwort
        noch braucht, sollte es vorher anzeigen und an einem sicheren Ort ablegen.
      </p>
    </ConfirmDialog>
  );
}
