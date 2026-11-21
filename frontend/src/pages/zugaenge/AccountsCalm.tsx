import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Account, type System } from "../../lib/api";
import ConfirmDialog from "../../components/ConfirmDialog";
import OverflowMenu, { type OverflowItem } from "../../components/OverflowMenu";
import { Skeleton } from "../../components/Skeleton";
import { useRevealedSecrets } from "../../lib/useRevealedSecrets";
import { useUndoToast } from "../../lib/useUndoToast";
import { useUrlState } from "../../lib/useUrlState";
import { CATEGORY_LABEL } from "./categories";
import { takeAccountsFlash } from "./accountDraft";
import DeleteAccountDialog from "./DeleteAccountDialog";
import "../mehr/mehr.css";

/**
 * "Zugänge" in the redesigned UI (docs/redesign/5-information-architecture.md).
 * A calm list with the search in `?q=`; "Neuer Zugang" and
 * editing are their own routes (`/zugaenge/neu`, `/zugaenge/:id`, AccountFormCalm.tsx), so Back
 * no longer throws a half-filled form away. Every call is one the classic page already makes.
 *
 * Secrets: shown one at a time via the existing `revealSecret` and hidden again after 30 s
 * (lib/useRevealedSecrets.ts); never in storage or the URL. Deleting goes through a review step that
 * names what is lost and says there is no undo (DeleteAccountDialog.tsx).
 */

const PM_NOTICE_KEY = "homeatlas.zugaenge.pmNoticeSeen";

function readSeen(): boolean {
  try {
    return window.localStorage.getItem(PM_NOTICE_KEY) === "1";
  } catch {
    return false;
  }
}

function PasswordManagerText() {
  return (
    <>
      <p>
        <strong>HomeAtlas ist kein Passwort-Manager.</strong> Was hier steht, gehört zur Dokumentation
        der Technik: Router-Zugang, NAS-Login, Kundennummer beim Anbieter, damit man im Störungsfall
        schnell drankommt.
      </p>
      <p>
        Für persönliche Passwörter, Bankzugänge und alles, was über einzelne Geräte hinausgeht, gehört
        ein echter Passwort-Safe her:{" "}
        <a href="https://bitwarden.com/" target="_blank" rel="noreferrer">Bitwarden</a> (auch selbst
        gehostet als <a href="https://github.com/dani-garcia/vaultwarden" target="_blank" rel="noreferrer">Vaultwarden</a>),{" "}
        <a href="https://keepassxc.org/" target="_blank" rel="noreferrer">KeePassXC</a> oder{" "}
        <a href="https://1password.com/" target="_blank" rel="noreferrer">1Password</a>. Passwörter
        werden hier verschlüsselt gespeichert, erscheinen nie in der Dokumentation und werden dem
        KI-Assistenten nie übergeben.
      </p>
    </>
  );
}

function ListSkeleton() {
  return (
    <div role="status" aria-live="polite">
      <span className="visually-hidden">Wird geladen …</span>
      <div className="m-toolbar"><Skeleton width="100%" height={40} radius={8} /></div>
      <Skeleton width={180} height={12} style={{ margin: "12px 0" }} />
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="m-skel-row">
          <div style={{ flex: 1, display: "grid", gap: 6 }}>
            <Skeleton width={`${40 + ((i * 17) % 35)}%`} />
            <Skeleton width="30%" height={10} />
          </div>
          <Skeleton width={80} height={12} />
        </div>
      ))}
    </div>
  );
}

export default function AccountsCalm() {
  const navigate = useNavigate();
  const [query, setQuery] = useUrlState("q");
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [systems, setSystems] = useState<System[]>([]);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [pmSeen, setPmSeen] = useState(readSeen);
  const [pmOpen, setPmOpen] = useState(false);
  const { secrets, reveal, hide } = useRevealedSecrets();
  const [toast, showToast] = useUndoToast();
  const [deleting, setDeleting] = useState<Account | null>(null);
  const [deploy, setDeploy] = useState<{ account: Account; loginId: string; error: string } | null>(null);
  const [deployBusy, setDeployBusy] = useState(false);

  async function reload() {
    const [a, s] = await Promise.all([api.listAccounts(), api.listSystems()]);
    setAccounts(a.accounts);
    setSystems(s.systems);
    setKindLabels(s.kindLabels);
  }

  useEffect(() => {
    reload().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    const flash = takeAccountsFlash();
    if (flash) showToast({ message: flash });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const systemName = useMemo(
    () => Object.fromEntries(systems.map((s) => [s.id, s.name])) as Record<string, string>,
    [systems],
  );

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!accounts) return [];
    if (!needle) return accounts;
    // Same fields as the classic search.
    return accounts.filter((a) =>
      [a.label, a.username, a.url, a.notes, systemName[a.systemId ?? ""] ?? ""].join(" ").toLowerCase().includes(needle),
    );
  }, [accounts, query, systemName]);

  function dismissNotice() {
    try {
      window.localStorage.setItem(PM_NOTICE_KEY, "1");
    } catch {
      /* storage blocked: the notice just shows again next time */
    }
    setPmSeen(true);
    setPmOpen(false);
  }

  async function onReveal(id: string) {
    setError("");
    try {
      await reveal(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function runDeploy() {
    if (!deploy) return;
    if (!deploy.loginId) {
      setDeploy({ ...deploy, error: "Bitte zuerst den Zugang zum Einloggen wählen." });
      return;
    }
    setDeployBusy(true);
    try {
      const r = await api.deploySshKey(deploy.account.id, deploy.loginId);
      const device = systemName[deploy.account.systemId ?? ""] ?? "Gerät";
      setDeploy(null);
      showToast({ message: r.changed ? `Schlüssel auf „${device}“ eingespielt.` : `Der Schlüssel war auf „${device}“ schon hinterlegt.` });
    } catch (e) {
      setDeploy((d) => d && { ...d, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setDeployBusy(false);
    }
  }

  if (accounts === null) {
    return (
      <div className="mehr-calm zugaenge-calm">
        {error ? <div className="notice error" role="alert">{error}</div> : <ListSkeleton />}
      </div>
    );
  }

  const probing = accounts.filter((a) => a.allowProbe).length;
  const deployLogins = deploy
    ? accounts.filter((o) => o.systemId === deploy.account.systemId && o.id !== deploy.account.id && o.hasSecret)
    : [];
  const deployDevice = deploy ? systemName[deploy.account.systemId ?? ""] ?? "das Gerät" : "";

  return (
    <div className="mehr-calm zugaenge-calm">
      {toast}
      <h1 className="visually-hidden">Zugänge</h1>

      <DeleteAccountDialog
        account={deleting}
        systemName={systemName}
        kindLabels={kindLabels}
        onCancel={() => setDeleting(null)}
        onDeleted={(account) => {
          setDeleting(null);
          hide(account.id);
          setAccounts((current) => (current ?? []).filter((a) => a.id !== account.id));
          showToast({ message: `Zugang „${account.label}“ gelöscht.` });
          void reload().catch(() => {});
        }}
      />

      <ConfirmDialog
        open={deploy !== null}
        title="SSH-Schlüssel auf dem Gerät einspielen"
        busy={deployBusy}
        confirmLabel="Einspielen"
        consequences={deploy ? [
          <>HomeAtlas meldet sich mit dem gewählten Zugang per SSH an „{deployDevice}“ an.</>,
          <>Der öffentliche Teil von „{deploy.account.label}“ wird dort für diesen Benutzer als erlaubter Schlüssel eingetragen (falls er noch fehlt); sonst wird nichts geändert.</>,
        ] : undefined}
        onCancel={() => setDeploy(null)}
        onConfirm={runDeploy}
      >
        <div className="field">
          <label htmlFor="zg-deploy-login">Mit welchem Zugang einloggen?</label>
          {deployLogins.length === 0 ? (
            <p className="m-dialog-note">
              Für „{deployDevice}“ ist kein weiterer Zugang mit Passwort hinterlegt. Lege zuerst einen
              Login-Zugang für dieses Gerät an.
            </p>
          ) : (
            <select id="zg-deploy-login" value={deploy?.loginId ?? ""}
                    onChange={(e) => setDeploy((d) => d && { ...d, loginId: e.target.value, error: "" })}>
              <option value="">Zugang wählen …</option>
              {deployLogins.map((o) => <option key={o.id} value={o.id}>{o.label}{o.username ? ` (${o.username})` : ""}</option>)}
            </select>
          )}
        </div>
        {deploy?.error && <div className="notice error" role="alert">{deploy.error}</div>}
      </ConfirmDialog>

      {pmSeen ? null : (
        <div className="m-note" role="note">
          <PasswordManagerText />
          <button type="button" className="m-btn small" onClick={dismissNotice}>Verstanden</button>
        </div>
      )}

      <div className="m-toolbar">
        <input className="m-search" type="search" aria-label="Zugänge durchsuchen" value={query}
               placeholder="Suchen nach Bezeichnung, Benutzername, Gerät, Notiz …"
               onChange={(e) => setQuery(e.target.value)} />
        <Link className="m-btn primary" to="/zugaenge/neu">+ Neuer Zugang</Link>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      <p className="m-summary">
        <b>{accounts.length}</b> {accounts.length === 1 ? "Zugang" : "Zugänge"}
        {probing > 0 && <> · <b>{probing}</b> {probing === 1 ? "liest" : "lesen"} Geräte aus</>}
        {query.trim() && accounts.length > 0 && <> · <b>{visible.length}</b> passen zur Suche</>}
        {pmSeen && (
          <>
            {" · "}
            <button type="button" className="m-link" aria-expanded={pmOpen} onClick={() => setPmOpen((v) => !v)}>
              ⓘ Kein Passwort-Manager
            </button>
          </>
        )}
      </p>
      {pmSeen && pmOpen && <div className="m-note"><PasswordManagerText /></div>}

      {accounts.length === 0 ? (
        <div className="m-empty">
          <h2>Noch keine Zugänge</h2>
          <p>
            Router-Zugang, NAS-Login, Kundennummer beim Anbieter: was man im Störungsfall braucht. Mit
            Zugängen für UniFi, Proxmox oder Home Assistant liest der Scan außerdem mehr aus.
          </p>
          <Link className="m-btn primary" to="/zugaenge/neu">Ersten Zugang anlegen</Link>
        </div>
      ) : visible.length === 0 ? (
        <div className="m-empty">
          <p>Kein Zugang passt zu „{query}“.</p>
          <button type="button" className="m-btn" onClick={() => setQuery("")}>Suche löschen</button>
        </div>
      ) : (
        <ul className="m-rows" aria-label="Zugänge">
          {visible.map((a) => {
            const device = a.systemId ? systemName[a.systemId] ?? "unbekanntes Gerät" : "";
            const items: OverflowItem[] = [
              { label: "Bearbeiten", onSelect: () => navigate(`/zugaenge/${a.id}`) },
              ...(a.category === "sshkey" && a.systemId
                ? [{ label: "Auf Gerät einspielen …", onSelect: () => setDeploy({ account: a, loginId: "", error: "" }) }]
                : []),
              { label: "Löschen …", onSelect: () => setDeleting(a), danger: true },
            ];
            return (
              <li key={a.id} className="m-row" data-testid="account-row">
                <div className="m-row-main">
                  <span className="m-row-title">
                    <Link className="m-row-name" to={`/zugaenge/${a.id}`}>{a.label}</Link>
                    {a.allowProbe ? <span className="m-chip ok" title="Wird zum Auslesen des Geräts verwendet"><span className="dot" aria-hidden="true" />liest aus</span> : null}
                    {(a.assignmentCount ?? 0) > 0 && (
                      <span className="m-tag" title="Gilt zusätzlich für weitere Gerätekategorien/Subnetze/Geräte">
                        gilt für {a.assignmentCount} weitere
                      </span>
                    )}
                  </span>
                  <span className="m-row-sub">
                    {CATEGORY_LABEL[a.category] ?? a.category}
                    {a.username && <> · <span className="mono">{a.username}</span></>}
                    {device && <> · <Link to={`/geraete/${a.systemId}`}>{device}</Link></>}
                  </span>
                  {a.url && (
                    <span className="m-row-sub"><a href={a.url} target="_blank" rel="noreferrer">{a.url}</a></span>
                  )}
                  {a.notes && <span className="m-row-sub">{a.notes}</span>}
                </div>
                <div className="m-row-side">
                  <span className="m-secret">
                    {!a.hasSecret ? (
                      <span className="m-row-sub">kein Passwort</span>
                    ) : secrets[a.id] !== undefined ? (
                      <>
                        <code className="mono m-secret-value" data-testid="secret-value">{secrets[a.id]}</code>
                        <button type="button" className="m-btn small" onClick={() => hide(a.id)}>Verbergen</button>
                        <span className="m-row-sub">verbirgt sich nach 30 s</span>
                      </>
                    ) : (
                      <button type="button" className="m-btn small" onClick={() => void onReveal(a.id)}
                              aria-label={`Passwort von ${a.label} anzeigen`}>
                        Anzeigen
                      </button>
                    )}
                  </span>
                  <OverflowMenu items={items} label={`Aktionen für ${a.label}`} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
