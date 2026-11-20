/** Explains every access-log action in plain words (both UIs). A log that only shows
 *  `secret.reveal` helps nobody who wants to know whether someone looked at the passwords. */
export const ACTION_LABEL: Record<string, string> = {
  login: "Anmeldung",
  "login.mfa": "Zwei-Faktor-Abfrage",
  "password.change": "Passwort geändert",
  "mfa.enable": "Zwei-Faktor aktiviert",
  "mfa.disable": "Zwei-Faktor abgeschaltet",
  "mfa.reset": "Zwei-Faktor zurückgesetzt",
  "user.create": "Benutzer angelegt",
  "user.update": "Benutzer geändert",
  "user.delete": "Benutzer gelöscht",
  "secret.reveal": "Passwort angezeigt",
  "scan.start": "Netzwerk-Scan gestartet",
};

export const CRITICAL_ACTIONS = new Set(["secret.reveal", "mfa.disable", "mfa.reset", "user.create", "user.update", "user.delete"]);
