import { useRef, useState, type FormEvent } from "react";
import { ApiError, api } from "../lib/api";
import GateShell, { GateBrand } from "./GateShell";

/**
 * Login. Two-step flow: the backend answers 401 with
 * `X-HomeAtlas-MFA: required` when the password was right and the second factor is still missing,
 * and only then does the code field appear. No new features (no "forgot password").
 *
 * Nothing typed here is stored anywhere: the password and the code live in component state only.
 */

function loginError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  // fetch() itself failed: no answer from the server at all.
  if (err instanceof TypeError) return "Der Server ist gerade nicht erreichbar. Bitte gleich noch einmal versuchen.";
  return err instanceof Error ? err.message : "Anmeldung fehlgeschlagen.";
}

export default function LoginCalm({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [totpCode, setTotpCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!username.trim() || !password) {
      setError("Bitte Benutzername und Passwort eingeben.");
      (username.trim() ? passwordRef : usernameRef).current?.focus();
      return;
    }
    if (needsCode && totpCode.length < 6) {
      setError("Bitte den 6-stelligen Code aus der Authenticator-App eingeben.");
      codeRef.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.login(username, password, totpCode);
      onLoggedIn();
    } catch (err) {
      if (err instanceof ApiError && err.mfaRequired) {
        setNeedsCode(true);
        setTotpCode("");
        window.setTimeout(() => codeRef.current?.focus(), 0);
      } else {
        // Wrong password: keep the name, clear the password, put the cursor back there.
        setPassword("");
        window.setTimeout(() => passwordRef.current?.focus(), 0);
      }
      setError(loginError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <GateShell>
      <GateBrand sub="Dein Zuhause, dokumentiert" />
      <h1 className="gate-title">Anmelden</h1>

      <form onSubmit={submit} noValidate>
        {error && <div className="gate-error" role="alert">{error}</div>}

        <div className="gate-field">
          <label htmlFor="gate-username">Benutzername</label>
          <input id="gate-username" ref={usernameRef} value={username} autoFocus autoComplete="username"
                 autoCapitalize="none" autoCorrect="off" spellCheck={false} enterKeyHint="next"
                 onChange={(e) => setUsername(e.target.value)} />
        </div>

        <div className="gate-field">
          <label htmlFor="gate-password">Passwort</label>
          <div className="gate-password">
            <input id="gate-password" ref={passwordRef} type={showPassword ? "text" : "password"} value={password}
                   autoComplete="current-password" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                   enterKeyHint={needsCode ? "next" : "go"}
                   onChange={(e) => setPassword(e.target.value)} />
            <button type="button" className="gate-reveal" aria-controls="gate-password"
                    aria-label={showPassword ? "Passwort verbergen" : "Passwort anzeigen"}
                    onClick={() => setShowPassword((v) => !v)}>
              {showPassword ? "Verbergen" : "Anzeigen"}
            </button>
          </div>
        </div>

        {needsCode && (
          <div className="gate-field">
            <label htmlFor="gate-totp">Code aus der Authenticator-App</label>
            <input id="gate-totp" ref={codeRef} className="gate-code" inputMode="numeric" autoComplete="one-time-code"
                   pattern="[0-9]*" maxLength={6} placeholder="6-stellig" enterKeyHint="go" value={totpCode}
                   onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))} />
            <div className="gate-hint">Der Code wechselt alle 30 Sekunden.</div>
          </div>
        )}

        <button type="submit" className="gate-primary" disabled={busy}>
          {busy ? "Anmelden…" : "Anmelden"}
        </button>
      </form>

      <details className="gate-details">
        <summary>Erster Start?</summary>
        <p>
          Beim allerersten Start steht das Passwort einmalig im Server-Protokoll:{" "}
          <code>docker compose logs backend</code>
        </p>
      </details>
    </GateShell>
  );
}
