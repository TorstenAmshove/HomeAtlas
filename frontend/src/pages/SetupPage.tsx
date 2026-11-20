import { useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../App";
import ConfirmDialog from "../components/ConfirmDialog";
import {
  ACCOUNT_CATEGORIES, KINDS, emptyAccount, emptySystem, initialSetupForm, isSetupDirty,
  type AccountDraft, type SystemDraft,
} from "../gates/setupModel";

/** First-run wizard. Asks for the handful of things a network scan can never discover on its own:
 *  what the household calls itself, which systems matter, and the logins that go with them.
 *  The redesigned UI shows gates/SetupCalm.tsx instead; both share gates/setupModel.ts. */

export default function SetupPage({ onDone }: { onDone: () => void }) {
  const { logout } = useAuth();
  const [initial] = useState(initialSetupForm);
  const [step, setStep] = useState(0);
  const [homeName, setHomeName] = useState(initial.homeName);
  const [subnet, setSubnet] = useState(initial.subnet);
  const [systems, setSystems] = useState<SystemDraft[]>(initial.systems);
  const [accounts, setAccounts] = useState<AccountDraft[]>(initial.accounts);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The way out of the wizard (docs/redesign/2-page-forensics.md: "Einrichtung hat keinen Ausweg").
  // Asks first once something was entered, since logging out throws the entries away.
  const [askLogout, setAskLogout] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const dirty = step > 0 || isSetupDirty({ homeName, subnet, systems, accounts });
  async function doLogout() {
    setLeaving(true);
    try {
      await logout();
    } finally {
      setLeaving(false);
      setAskLogout(false);
    }
  }

  function patchSystem(index: number, patch: Partial<SystemDraft>) {
    setSystems((current) => current.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  }
  function patchAccount(index: number, patch: Partial<AccountDraft>) {
    setAccounts((current) => current.map((a, i) => (i === index ? { ...a, ...patch } : a)));
  }

  async function finish() {
    setBusy(true);
    setError("");
    try {
      await api.setup({
        homeName,
        scanSubnets: subnet.trim() ? [subnet.trim()] : [],
        systems: systems.filter((s) => s.name.trim()),
        accounts: accounts.filter((a) => a.label.trim()),
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Speichern fehlgeschlagen.");
      setBusy(false);
    }
  }

  return (
    <div className="content" style={{ margin: "0 auto", maxWidth: 820 }}>
      <div className="page-header">
        <div>
          <h1>Willkommen bei HomeAtlas 🧭</h1>
          <p>
            Ein paar Angaben, dann kann HomeAtlas dein Netzwerk selbst durchsuchen und die
            Dokumentation schreiben. Alles lässt sich später ändern — es muss jetzt nichts perfekt sein.
          </p>
        </div>
        <div className="row">
          <span className="badge">Schritt {step + 1} von 3</span>
          <button className="secondary small" disabled={leaving}
                  onClick={() => (dirty ? setAskLogout(true) : void doLogout())}>
            Abmelden
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={askLogout}
        title="Abmelden?"
        consequences={[
          <>Deine Angaben aus der Einrichtung werden verworfen.</>,
          <>Nach dem nächsten Anmelden beginnt die Einrichtung wieder bei Schritt 1.</>,
        ]}
        confirmLabel="Trotzdem abmelden"
        cancelLabel="Angemeldet bleiben"
        danger
        busy={leaving}
        onConfirm={doLogout}
        onCancel={() => setAskLogout(false)}
      />

      {error && <div className="notice error">{error}</div>}

      {step === 0 && (
        <div className="card">
          <h2>1. Dein Zuhause</h2>
          <div className="field">
            <label htmlFor="homeName">Wie soll dein Zuhause heißen?</label>
            <input id="homeName" value={homeName} onChange={(e) => setHomeName(e.target.value)} />
            <div className="field-hint">Erscheint als Überschrift in der Dokumentation, z. B. „Familie Meier".</div>
          </div>
          <div className="field">
            <label htmlFor="subnet">Netzwerk-Bereich (optional)</label>
            <input id="subnet" placeholder="z. B. 192.168.1.0/24" value={subnet}
                   onChange={(e) => setSubnet(e.target.value)} />
            <div className="field-hint">
              Leer lassen, wenn du unsicher bist — HomeAtlas erkennt den Bereich dann automatisch.
            </div>
          </div>
          <button onClick={() => setStep(1)}>Weiter</button>
        </div>
      )}

      {step === 1 && (
        <div className="card">
          <h2>2. Die wichtigsten Geräte</h2>
          <p className="muted">
            Trage ein, was du sicher weißt — vor allem Router, Server und alles, was bei einem Ausfall
            im Haus auffällt. Den Rest findet der Netzwerk-Scan später selbst.
          </p>

          {systems.map((system, index) => (
            <div key={index} className="card" style={{ background: "var(--bg)", marginTop: 14 }}>
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
                <strong>Gerät {index + 1}</strong>
                {systems.length > 1 && (
                  <button className="danger small"
                          onClick={() => setSystems((c) => c.filter((_, i) => i !== index))}>
                    Entfernen
                  </button>
                )}
              </div>
              <div className="grid cols-2">
                <div className="field">
                  <label>Name</label>
                  <input placeholder="z. B. FRITZ!Box im Flur" value={system.name}
                         onChange={(e) => patchSystem(index, { name: e.target.value })} />
                </div>
                <div className="field">
                  <label>Was ist das?</label>
                  <select value={system.kind} onChange={(e) => patchSystem(index, { kind: e.target.value })}>
                    {KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Adresse im Netzwerk (optional)</label>
                  <input placeholder="z. B. 192.168.1.1" value={system.ip}
                         onChange={(e) => patchSystem(index, { ip: e.target.value })} />
                </div>
                <div className="field">
                  <label>Standort (optional)</label>
                  <input placeholder="z. B. Keller, Arbeitszimmer" value={system.location}
                         onChange={(e) => patchSystem(index, { location: e.target.value })} />
                </div>
                <div className="field">
                  <label>Benutzername (optional)</label>
                  <input value={system.username} autoComplete="off"
                         onChange={(e) => patchSystem(index, { username: e.target.value })} />
                </div>
                <div className="field">
                  <label>Passwort (optional)</label>
                  <input type="password" value={system.password} autoComplete="new-password"
                         onChange={(e) => patchSystem(index, { password: e.target.value })} />
                  <div className="field-hint">Wird verschlüsselt gespeichert.</div>
                </div>
              </div>
            </div>
          ))}

          <div className="row" style={{ marginTop: 16 }}>
            <button className="secondary" onClick={() => setSystems((c) => [...c, emptySystem()])}>
              + Weiteres Gerät
            </button>
            <button className="secondary" onClick={() => setStep(0)}>Zurück</button>
            <button onClick={() => setStep(2)}>Weiter</button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="card">
          <h2>3. Wichtige Konten</h2>
          <p className="muted">
            Zugänge, die nicht zu einem einzelnen Gerät gehören: Internetanbieter, DynDNS,
            Cloud-Dienste, das WLAN-Passwort. Passwörter werden verschlüsselt abgelegt und tauchen
            weder in der Dokumentation noch beim KI-Assistenten auf.
          </p>

          {accounts.map((account, index) => (
            <div key={index} className="card" style={{ background: "var(--bg)", marginTop: 14 }}>
              <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
                <strong>Konto {index + 1}</strong>
                {accounts.length > 1 && (
                  <button className="danger small"
                          onClick={() => setAccounts((c) => c.filter((_, i) => i !== index))}>
                    Entfernen
                  </button>
                )}
              </div>
              <div className="grid cols-2">
                <div className="field">
                  <label>Bezeichnung</label>
                  <input placeholder="z. B. Telekom Kundenkonto" value={account.label}
                         onChange={(e) => patchAccount(index, { label: e.target.value })} />
                </div>
                <div className="field">
                  <label>Art</label>
                  <select value={account.category}
                          onChange={(e) => patchAccount(index, { category: e.target.value })}>
                    {ACCOUNT_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Benutzername / Kundennummer</label>
                  <input value={account.username} autoComplete="off"
                         onChange={(e) => patchAccount(index, { username: e.target.value })} />
                </div>
                <div className="field">
                  <label>Passwort</label>
                  <input type="password" value={account.secret} autoComplete="new-password"
                         onChange={(e) => patchAccount(index, { secret: e.target.value })} />
                </div>
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label>Notiz (optional)</label>
                  <input placeholder="z. B. Hotline 0800 …, Vertrag läuft bis …" value={account.notes}
                         onChange={(e) => patchAccount(index, { notes: e.target.value })} />
                </div>
              </div>
            </div>
          ))}

          <div className="row" style={{ marginTop: 16 }}>
            <button className="secondary" onClick={() => setAccounts((c) => [...c, emptyAccount()])}>
              + Weiteres Konto
            </button>
            <button className="secondary" onClick={() => setStep(1)}>Zurück</button>
            <button onClick={() => void finish()} disabled={busy}>
              {busy ? "Speichern…" : "Fertig — los geht's"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
