import { useRef, useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { useAuth } from "../App";
import GateShell, { GateBrand } from "./GateShell";

/**
 * Mandatory second-factor enrollment. Two requests: `mfaSetup` creates a not yet
 * active secret, `mfaConfirm` activates it with a working code -- the backend enforces that nothing
 * else is reachable until then (`deps.current_user`).
 *
 * The secret is held in component state only: never in sessionStorage/localStorage, never logged.
 * "Abmelden" stays visible the whole time, so nobody is stuck just because the phone is missing.
 */

/** Groups of four for reading and typing; authenticator apps ignore the spaces. */
const grouped = (secret: string) => secret.replace(/(.{4})(?=.)/g, "$1 ");

export default function MfaEnroll({ onDone }: { onDone: () => void }) {
  const { user, logout } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; qrSvg: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<"" | "copied" | "selected">("");
  const [leaving, setLeaving] = useState(false);
  const secretRef = useRef<HTMLElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);

  async function start() {
    setBusy(true);
    setError("");
    try {
      const result = await api.mfaSetup();
      setSetup({ secret: result.secret, qrSvg: result.qrSvg });
      setCopied("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (code.length < 6) {
      setError("Bitte den 6-stelligen Code aus der App eingeben.");
      codeRef.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.mfaConfirm(code);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setCode("");
      window.setTimeout(() => codeRef.current?.focus(), 0);
    } finally {
      setBusy(false);
    }
  }

  /** Clipboard API where available (HTTPS or localhost); otherwise the key is selected, so the
   *  usual "copy" of the device works -- plain HTTP on the LAN is the normal case for HomeAtlas. */
  async function copySecret() {
    if (!setup) return;
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("no clipboard");
      await navigator.clipboard.writeText(setup.secret);
      setCopied("copied");
    } catch {
      const node = secretRef.current;
      const selection = window.getSelection();
      if (node && selection) {
        const range = document.createRange();
        range.selectNodeContents(node);
        selection.removeAllRanges();
        selection.addRange(range);
      }
      setCopied("selected");
    }
  }

  async function leave() {
    setLeaving(true);
    try {
      await logout();
    } catch (e) {
      setError(`Abmelden hat nicht geklappt (${e instanceof Error ? e.message : String(e)}). Du bist noch angemeldet.`);
    } finally {
      setLeaving(false);
    }
  }

  return (
    <GateShell>
      <GateBrand sub={<>Angemeldet als {user?.displayName || user?.username}</>} />
      <h1 className="gate-title">Zwei-Faktor-Anmeldung einrichten</h1>
      <p className="gate-lead">
        Zusätzlich zum Passwort fragt HomeAtlas nach einem Code aus einer Authenticator-App. Ohne
        Einrichtung geht es hier nicht weiter. Geht das Handy mit der App verloren, kann ein
        Administrator den zweiten Faktor zurücksetzen.
      </p>

      {error && <div className="gate-error" role="alert">{error}</div>}

      <ol className="gate-howto">
        <li className={setup ? "done" : "current"}>
          <span className="gate-howto-n" aria-hidden="true">1</span>
          <div>
            <strong>App öffnen</strong>
            <div className="gate-hint">z. B. Aegis, 2FAS, Google Authenticator, 1Password</div>
          </div>
        </li>
        <li className={setup ? "current" : ""}>
          <span className="gate-howto-n" aria-hidden="true">2</span>
          <div>
            <strong>QR scannen (oder Code eingeben)</strong>
            {setup && (
              <div className="gate-qr-block">
                {setup.qrSvg ? (
                  // Server-rendered SVG (backend `security.qr_svg`), shown as-is.
                  <div className="gate-qr" role="img" aria-label="QR-Code für die Authenticator-App"
                       dangerouslySetInnerHTML={{ __html: setup.qrSvg }} />
                ) : (
                  <div className="gate-note">
                    QR-Code konnte nicht erzeugt werden. Bitte den Schlüssel unten von Hand eintragen.
                  </div>
                )}
                <div className="gate-secret-label" id="gate-secret-label">Schlüssel zum Abtippen</div>
                <div className="gate-secret-row">
                  <code ref={secretRef} className="gate-secret mono" aria-labelledby="gate-secret-label">{grouped(setup.secret)}</code>
                  <button type="button" className="gate-secondary" onClick={() => void copySecret()}>
                    {copied === "copied" ? "Kopiert" : "Kopieren"}
                  </button>
                </div>
                <div className="gate-hint" aria-live="polite">
                  {copied === "copied" && "Schlüssel in der Zwischenablage."}
                  {copied === "selected" && "Schlüssel markiert. Jetzt kopieren (Strg+C bzw. ⌘C oder lange tippen)."}
                </div>
              </div>
            )}
          </div>
        </li>
        <li>
          <span className="gate-howto-n" aria-hidden="true">3</span>
          <div>
            <strong>Code eingeben</strong>
            {setup && (
              <form onSubmit={confirm} noValidate className="gate-code-form">
                <label htmlFor="gate-mfa-code" className="visually-hidden">Code aus der Authenticator-App</label>
                <input id="gate-mfa-code" ref={codeRef} className="gate-code" inputMode="numeric"
                       autoComplete="one-time-code" pattern="[0-9]*" maxLength={6} placeholder="6-stellig"
                       enterKeyHint="go" value={code}
                       onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
                <button type="submit" className="gate-primary" disabled={busy}>
                  {busy ? "Prüfe…" : "Aktivieren"}
                </button>
              </form>
            )}
          </div>
        </li>
      </ol>

      {!setup && (
        <button type="button" className="gate-primary" onClick={() => void start()} disabled={busy} autoFocus>
          {busy ? "Erzeuge…" : "Einrichtung starten"}
        </button>
      )}

      <div className="gate-foot">
        <button type="button" className="gate-link" onClick={() => void leave()} disabled={leaving}>
          Abmelden
        </button>
      </div>
    </GateShell>
  );
}
