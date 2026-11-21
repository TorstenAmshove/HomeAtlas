import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { useAuth } from "../App";
import ConfirmDialog from "../components/ConfirmDialog";
import GateShell, { GateBrand } from "./GateShell";
import {
  ACCOUNT_CATEGORIES, KINDS, clearSetupDraft, emptyAccount, emptySystem, hasTypedSecrets, initialSetupForm,
  isSetupDirty, loadSetupDraft, saveSetupDraft, setupBody, type AccountDraft, type SetupForm, type SystemDraft,
} from "./setupModel";

/**
 * First-run wizard in the redesigned UI (instead of pages/SetupPage.tsx while `uiCalm` resolves to
 * on). Same three steps and the same `POST /api/setup` body as the classic page (gates/setupModel.ts).
 *
 * Onboarding rules (docs/redesign, IN-APP): until it is finished only the wizard shows, and nobody
 * gets stuck in it -- "Abmelden" is on every step (forensics: "Einrichtung hat keinen Ausweg").
 * There is deliberately no "skip": the backend gate requires completion for admins.
 *
 * The household data survives a reload (sessionStorage draft, cleared on logout and on finishing);
 * passwords never go into it, see setupModel.ts.
 */

const STEPS = ["Zuhause", "Geräte", "Konten"];

export default function SetupCalm({ onDone }: { onDone: () => void }) {
  const { user, logout } = useAuth();
  const userId = user?.id ?? "";
  const [restored] = useState(() => loadSetupDraft(userId));
  const [step, setStep] = useState(restored?.step ?? 0);
  const [form, setForm] = useState<SetupForm>(restored?.form ?? initialSetupForm());
  const [secretsDropped] = useState(restored?.hadSecrets ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [askLogout, setAskLogout] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  const secretsMissing = secretsDropped && !hasTypedSecrets(form);
  const dirty = step > 0 || isSetupDirty(form);

  useEffect(() => {
    if (!dirty) clearSetupDraft();
    else saveSetupDraft(userId, step, form, secretsMissing);
  }, [userId, step, form, dirty, secretsMissing]);

  // A new step moves focus to its heading, so keyboard and screen-reader users start at the top.
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    headingRef.current?.focus();
    window.scrollTo({ top: 0 });
  }, [step]);

  const patch = (p: Partial<SetupForm>) => setForm((f) => ({ ...f, ...p }));
  const patchSystem = (index: number, p: Partial<SystemDraft>) =>
    setForm((f) => ({ ...f, systems: f.systems.map((s, i) => (i === index ? { ...s, ...p } : s)) }));
  const patchAccount = (index: number, p: Partial<AccountDraft>) =>
    setForm((f) => ({ ...f, accounts: f.accounts.map((a, i) => (i === index ? { ...a, ...p } : a)) }));

  async function finish() {
    setBusy(true);
    setError("");
    try {
      await api.setup(setupBody(form));
      clearSetupDraft();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Speichern fehlgeschlagen.");
      setBusy(false);
      window.setTimeout(() => errorRef.current?.focus(), 0);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (step < STEPS.length - 1) setStep(step + 1);
    else void finish();
  }

  async function doLogout() {
    setLeaving(true);
    try {
      await logout(); // also clears this tab's drafts, the wizard's included
    } catch (e) {
      setError(`Abmelden hat nicht geklappt (${e instanceof Error ? e.message : String(e)}). Du bist noch angemeldet.`);
    } finally {
      setLeaving(false);
      setAskLogout(false);
    }
  }

  const knownName = step > 0 && form.homeName.trim() ? form.homeName.trim() : "HomeAtlas";

  return (
    <GateShell wide>
      <GateBrand
        title={knownName}
        sub="Einrichtung"
        aside={
          <button type="button" className="gate-link gate-brand-aside" disabled={leaving}
                  onClick={() => (dirty ? setAskLogout(true) : void doLogout())}>
            Abmelden
          </button>
        }
      />

      <ol className="gate-steps" aria-label="Schritte der Einrichtung">
        {STEPS.map((label, i) => (
          <li key={label} className={i === step ? "current" : i < step ? "done" : ""}
              aria-current={i === step ? "step" : undefined}>
            <span className="gate-steps-n" aria-hidden="true">{i + 1}</span>
            <span className="gate-steps-label">{label}</span>
          </li>
        ))}
      </ol>

      <form onSubmit={submit} noValidate>
        {error && <div className="gate-error" role="alert" tabIndex={-1} ref={errorRef}>{error}</div>}
        {secretsMissing && (
          <div className="gate-note">
            Passwörter und Notizen werden aus Sicherheitsgründen nicht zwischengespeichert. Nach dem
            Neuladen bitte die Passwort- und Notiz-Felder erneut ausfüllen (oder später unter Zugänge nachtragen).
          </div>
        )}

        {step === 0 && (
          <section aria-labelledby="setup-step-title">
            <h1 className="gate-title" id="setup-step-title" ref={headingRef} tabIndex={-1}>
              Willkommen bei HomeAtlas
            </h1>
            <p className="gate-lead">
              Ein paar Angaben, dann kann HomeAtlas dein Netzwerk selbst durchsuchen und die
              Dokumentation schreiben. Alles lässt sich später ändern.
            </p>
            <div className="gate-field">
              <label htmlFor="homeName">Wie soll dein Zuhause heißen?</label>
              <input id="homeName" value={form.homeName} autoFocus enterKeyHint="next"
                     onChange={(e) => patch({ homeName: e.target.value })} />
              <div className="gate-hint">Erscheint als Überschrift in der Dokumentation, z. B. „Familie Meier".</div>
            </div>
            <div className="gate-field">
              <label htmlFor="subnet">Netzwerk-Bereich (optional)</label>
              <input id="subnet" placeholder="z. B. 192.168.1.0/24" value={form.subnet} enterKeyHint="next"
                     autoCapitalize="none" autoCorrect="off" spellCheck={false}
                     onChange={(e) => patch({ subnet: e.target.value })} />
              <div className="gate-hint">Leer lassen, wenn du unsicher bist. HomeAtlas erkennt den Bereich dann selbst.</div>
            </div>
          </section>
        )}

        {step === 1 && (
          <section aria-labelledby="setup-step-title">
            <h1 className="gate-title" id="setup-step-title" ref={headingRef} tabIndex={-1}>
              Die wichtigsten Geräte
            </h1>
            <p className="gate-lead">
              Trage ein, was du sicher weißt: vor allem Router, Server und alles, was bei einem Ausfall
              im Haus auffällt. Den Rest findet der Netzwerk-Scan später selbst.
            </p>
            {form.systems.map((system, index) => (
              <fieldset key={index} className="gate-item">
                <legend className="gate-item-head">
                  <span>Gerät {index + 1}</span>
                </legend>
                <div className="gate-grid">
                  <div className="gate-field">
                    <label htmlFor={`sys-name-${index}`}>Name</label>
                    <input id={`sys-name-${index}`} placeholder="z. B. FRITZ!Box im Flur" value={system.name}
                           onChange={(e) => patchSystem(index, { name: e.target.value })} />
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`sys-kind-${index}`}>Was ist das?</label>
                    <select id={`sys-kind-${index}`} value={system.kind}
                            onChange={(e) => patchSystem(index, { kind: e.target.value })}>
                      {KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`sys-ip-${index}`}>Adresse im Netzwerk (optional)</label>
                    <input id={`sys-ip-${index}`} placeholder="z. B. 192.168.1.1" value={system.ip}
                           inputMode="url" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                           onChange={(e) => patchSystem(index, { ip: e.target.value })} />
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`sys-loc-${index}`}>Standort (optional)</label>
                    <input id={`sys-loc-${index}`} placeholder="z. B. Keller, Arbeitszimmer" value={system.location}
                           onChange={(e) => patchSystem(index, { location: e.target.value })} />
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`sys-user-${index}`}>Benutzername (optional)</label>
                    <input id={`sys-user-${index}`} value={system.username} autoComplete="off"
                           autoCapitalize="none" autoCorrect="off" spellCheck={false}
                           onChange={(e) => patchSystem(index, { username: e.target.value })} />
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`sys-pass-${index}`}>Passwort (optional)</label>
                    <input id={`sys-pass-${index}`} type="password" value={system.password} autoComplete="new-password"
                           onChange={(e) => patchSystem(index, { password: e.target.value })} />
                    <div className="gate-hint">Wird verschlüsselt gespeichert.</div>
                  </div>
                </div>
                <div className="gate-item-foot">
                  {form.systems.length > 1 && (
                    <button type="button" className="gate-link"
                            aria-label={`Gerät ${index + 1} entfernen`}
                            onClick={() => setForm((f) => ({ ...f, systems: f.systems.filter((_, i) => i !== index) }))}>
                      Entfernen
                    </button>
                  )}
                </div>
              </fieldset>
            ))}
            <button type="button" className="gate-secondary"
                    onClick={() => setForm((f) => ({ ...f, systems: [...f.systems, emptySystem()] }))}>
              + Weiteres Gerät
            </button>
          </section>
        )}

        {step === 2 && (
          <section aria-labelledby="setup-step-title">
            <h1 className="gate-title" id="setup-step-title" ref={headingRef} tabIndex={-1}>
              Wichtige Konten
            </h1>
            <p className="gate-lead">
              Zugänge, die nicht zu einem einzelnen Gerät gehören: Internetanbieter, DynDNS,
              Cloud-Dienste, das WLAN-Passwort. Passwörter werden verschlüsselt abgelegt und tauchen
              weder in der Dokumentation noch beim KI-Assistenten auf.
            </p>
            {form.accounts.map((account, index) => (
              <fieldset key={index} className="gate-item">
                <legend className="gate-item-head">
                  <span>Konto {index + 1}</span>
                </legend>
                <div className="gate-grid">
                  <div className="gate-field">
                    <label htmlFor={`acc-label-${index}`}>Bezeichnung</label>
                    <input id={`acc-label-${index}`} placeholder="z. B. Telekom Kundenkonto" value={account.label}
                           onChange={(e) => patchAccount(index, { label: e.target.value })} />
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`acc-cat-${index}`}>Art</label>
                    <select id={`acc-cat-${index}`} value={account.category}
                            onChange={(e) => patchAccount(index, { category: e.target.value })}>
                      {ACCOUNT_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                    </select>
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`acc-user-${index}`}>Benutzername / Kundennummer</label>
                    <input id={`acc-user-${index}`} value={account.username} autoComplete="off"
                           autoCapitalize="none" autoCorrect="off" spellCheck={false}
                           onChange={(e) => patchAccount(index, { username: e.target.value })} />
                  </div>
                  <div className="gate-field">
                    <label htmlFor={`acc-pass-${index}`}>Passwort</label>
                    <input id={`acc-pass-${index}`} type="password" value={account.secret} autoComplete="new-password"
                           onChange={(e) => patchAccount(index, { secret: e.target.value })} />
                  </div>
                  <div className="gate-field gate-grid-full">
                    <label htmlFor={`acc-notes-${index}`}>Notiz (optional)</label>
                    <input id={`acc-notes-${index}`} placeholder="z. B. Hotline 0800 …, Vertrag läuft bis …" value={account.notes}
                           onChange={(e) => patchAccount(index, { notes: e.target.value })} />
                  </div>
                </div>
                <div className="gate-item-foot">
                  {form.accounts.length > 1 && (
                    <button type="button" className="gate-link"
                            aria-label={`Konto ${index + 1} entfernen`}
                            onClick={() => setForm((f) => ({ ...f, accounts: f.accounts.filter((_, i) => i !== index) }))}>
                      Entfernen
                    </button>
                  )}
                </div>
              </fieldset>
            ))}
            <button type="button" className="gate-secondary"
                    onClick={() => setForm((f) => ({ ...f, accounts: [...f.accounts, emptyAccount()] }))}>
              + Weiteres Konto
            </button>
          </section>
        )}

        <div className="gate-actions">
          {step > 0 && (
            <button type="button" className="gate-secondary" onClick={() => setStep(step - 1)} disabled={busy}>
              Zurück
            </button>
          )}
          {/* "Weiter" turns into "Fertig" in the same spot: the second click of a double click on
              "Weiter" (detail 2) must not submit the whole setup. Enter has detail 0. */}
          <button type="submit" className="gate-primary gate-next" disabled={busy}
                  onClick={(e) => { if (step === STEPS.length - 1 && e.detail > 1) e.preventDefault(); }}>
            {step < STEPS.length - 1 ? "Weiter" : busy ? "Speichern…" : "Fertig — los geht's"}
          </button>
        </div>
      </form>

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
    </GateShell>
  );
}
