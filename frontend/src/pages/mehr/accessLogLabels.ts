/** Explains every access-log action in plain words (both UIs). A log that only shows
 *  `secret.reveal` helps nobody who wants to know whether someone looked at the passwords. */
export const ACTION_LABEL: Record<string, string> = {
  login: "Anmeldung",
  "login.mfa": "Zwei-Faktor-Abfrage",
  "password.change": "Passwort geändert",
  "mfa.enable": "Zwei-Faktor aktiviert",
  "mfa.reset": "Zwei-Faktor zurückgesetzt",
  "user.create": "Benutzer angelegt",
  "user.update": "Benutzer geändert",
  "user.delete": "Benutzer gelöscht",
  "secret.reveal": "Passwort angezeigt",
  "account.create": "Zugang angelegt",
  "account.update": "Zugang geändert",
  "account.delete": "Zugang gelöscht",
  "networkresource.update": "Netzwerk-Notiz geändert",
  "scan.start": "Netzwerk-Scan gestartet",
  "switch.assistant": "Über den Assistenten geschaltet",
  // Altdaten: wird seit der Entfernung der Fernwartung (ADR-0023) nicht mehr geschrieben.
  "sshkey.generate": "SSH-Schlüssel erzeugt (alt)",
};

export const CRITICAL_ACTIONS = new Set(["secret.reveal", "account.create", "account.update", "account.delete", "mfa.reset", "user.create", "user.update", "user.delete", "switch.assistant"]);
