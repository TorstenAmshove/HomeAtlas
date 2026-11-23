import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Account } from "../../lib/api";
import { NoticeLine, Section, type Notice } from "./common";

/** How long a revealed password stays on screen (forensics "Gerät" 8). */
export const SECRET_VISIBLE_MS = 30_000;

/**
 * Tab "Zugänge" (admin only, as the card was before). Passwords come one at a time from the
 * existing admin-only `GET /api/accounts/{id}/secret` and hide themselves again after 30 s, so a
 * revealed secret does not stay readable on a screen someone walked away from. They are kept only
 * in this component's state, never in storage or the URL.
 */
export default function ZugaengeTab({ accounts }: {
  accounts: Account[];
}) {
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const timers = useRef<Record<string, number>>({});
  const [notice, setNotice] = useState<Notice>(null);

  useEffect(() => () => {
    Object.values(timers.current).forEach((t) => window.clearTimeout(t));
  }, []);

  function hide(accountId: string) {
    window.clearTimeout(timers.current[accountId]);
    delete timers.current[accountId];
    setSecrets((current) => {
      const next = { ...current };
      delete next[accountId];
      return next;
    });
  }

  async function reveal(accountId: string) {
    setNotice(null);
    try {
      const { secret } = await api.revealSecret(accountId);
      setSecrets((current) => ({ ...current, [accountId]: secret }));
      window.clearTimeout(timers.current[accountId]);
      timers.current[accountId] = window.setTimeout(() => hide(accountId), SECRET_VISIBLE_MS);
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div className="dv-tab-body">
      <Section title="Zugänge" id="dv-accounts"
               aside={<Link className="dv-link" to="/zugaenge">Zugänge verwalten</Link>}>
        <NoticeLine notice={notice} />
        {accounts.length === 0 ? (
          <p className="dv-empty">
            Für dieses Gerät ist kein Zugang hinterlegt — unter <Link to="/zugaenge">Zugänge</Link> lässt
            sich einer anlegen und diesem Gerät zuordnen.
          </p>
        ) : (
          <ul className="dv-rows">
            {accounts.map((a) => (
              <li key={a.id} className="dv-row dv-row-stack">
                <span className="dv-row-main">
                  <span className="dv-row-name">{a.label}</span>
                  {a.viaAssignment && (
                    <span className="dv-tag"
                          title="Nicht direkt diesem Gerät zugeordnet, sondern über eine Regel (Gerätekategorie/Subnetz/weiteres Gerät) auf der Zugänge-Seite">
                      über Zuordnung
                    </span>
                  )}
                </span>
                <span className="dv-row-sub">Benutzer: <span className="mono">{a.username || "—"}</span></span>
                <span className="dv-secret">
                  {!a.hasSecret ? (
                    <span className="dv-row-sub">kein Passwort hinterlegt</span>
                  ) : secrets[a.id] !== undefined ? (
                    <>
                      <code className="mono dv-secret-value" data-testid="secret-value">{secrets[a.id]}</code>
                      <button type="button" className="secondary dv-btn-small" onClick={() => hide(a.id)}>Verbergen</button>
                      <span className="dv-row-sub">wird nach 30 s wieder verborgen</span>
                    </>
                  ) : (
                    <button type="button" className="secondary dv-btn-small" onClick={() => void reveal(a.id)}>
                      Passwort anzeigen
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
