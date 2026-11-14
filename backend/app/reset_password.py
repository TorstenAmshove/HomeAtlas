"""Passwort- und Zwei-Faktor-Wiederherstellung von der Kommandozeile.

    docker compose exec backend python -m app.reset_password
    docker compose exec backend python -m app.reset_password <benutzer> <neues-passwort>
    docker compose exec backend python -m app.reset_password <benutzer> --reset-mfa
    docker compose exec backend python -m app.reset_password <benutzer> <neues-passwort> --reset-mfa

Reason this exists: the generated first-run password is printed exactly once, to the startup log
of the container that created it. If that container is gone (crash loop, `docker compose down`,
log rotation) while the data volume survives, the account exists and nobody can get in --
`ADMIN_PASSWORD` deliberately only applies when no user exists yet, so it is no way back.

The second factor has the same problem: there is no self-service "disable", only the admin route
`reset_user_mfa` in `main.py`. If the only admin loses their authenticator, nobody is left who
can call it. `--reset-mfa` does here what that route does (clear `totpSecretEnc`, set
`totpEnabled = False`, write an `mfa.reset` access-log entry) and additionally ends the user's
open sessions, so the next login goes through enrollment again.

`--reset-mfa` is an explicit flag rather than a side effect of every password reset on purpose:
losing the password and losing the phone are independent events, and clearing the factor opens a
window in which the password alone is enough to enroll a *new* authenticator. A plain password
reset therefore leaves an enrolled factor in place; the password argument is optional when only
the factor needs to go.

Running this requires shell access to the container, which already implies control of the host,
so it grants nothing an attacker in that position wouldn't have anyway.
"""
from __future__ import annotations

import secrets
import sys

from . import auth, db

_USAGE = "Aufruf: python -m app.reset_password [<benutzer> [<neues-passwort>] [--reset-mfa]]"
# Shown as the actor in the access log -- there is no logged-in user behind a CLI call.
_CLI_ACTOR = "(Kommandozeile)"


def main(argv: list[str]) -> int:
    db.init_db()

    reset_mfa = "--reset-mfa" in argv
    args = [a for a in argv if a != "--reset-mfa"]
    unknown = [a for a in args if a.startswith("--")]
    if unknown:
        print(f"Unbekannte Option: {unknown[0]}\n{_USAGE}", file=sys.stderr)
        return 2

    if len(args) == 0 and not reset_mfa:
        users = db.list_users()
        if not users:
            print("Es existiert noch kein Benutzer. Beim nächsten Start wird automatisch einer angelegt.")
            return 0
        print(f"{len(users)} Benutzer:")
        for user in users:
            mfa = "2FA aktiv" if user.get("totpEnabled") else "2FA nicht eingerichtet"
            print(f"  {user['username']:<20} {user['role']:<8} {mfa}")
        print("\nPasswort ändern:")
        print("  python -m app.reset_password <benutzer> <neues-passwort>")
        print("Zweiten Faktor zurücksetzen (z. B. Handy verloren):")
        print("  python -m app.reset_password <benutzer> --reset-mfa")
        return 0

    if len(args) == 1 and reset_mfa:
        username, password = args[0], None
    elif len(args) == 2:
        username, password = args
    else:
        print(_USAGE, file=sys.stderr)
        return 2

    if password is not None and len(password) < 8:
        print("Das Passwort muss mindestens 8 Zeichen haben.", file=sys.stderr)
        return 2

    user = db.get_user_by_username_raw(username)

    if user is None:
        if password is None:
            print(f"Benutzer '{username}' existiert nicht.", file=sys.stderr)
            return 1
        salt = secrets.token_hex(16)
        db.create_user(username, auth.hash_password(password, salt), salt, auth.ROLE_ADMIN)
        print(f"Benutzer '{username}' wurde neu als Administrator angelegt.")
        if reset_mfa:
            print("Ein neuer Benutzer hat noch keinen zweiten Faktor -- er wird beim ersten Anmelden eingerichtet.")
        return 0

    if password is not None:
        salt = secrets.token_hex(16)
        db.set_user_password(user["id"], auth.hash_password(password, salt), salt)
        print(f"Passwort für '{username}' ({user['role']}) wurde geändert.")

    if reset_mfa:
        # Same effect as `reset_user_mfa` in main.py. Ending the sessions as well is stricter than
        # the route (which relies on `current_user` gating them to enrollment): whoever runs this
        # is recovering a lost device, so nothing opened with it should stay alive.
        db.update_user(user["id"], {"totpSecretEnc": "", "totpEnabled": False})
        db.invalidate_user_sessions(user["id"])
        db.log_access("mfa.reset", username=_CLI_ACTOR, detail=username)
        print(f"Zweiter Faktor für '{username}' wurde entfernt, offene Sitzungen sind beendet.")
        print("Beim nächsten Anmelden wird die Zwei-Faktor-Anmeldung neu eingerichtet.")
    else:
        if user.get("totpEnabled"):
            print("Der zweite Faktor bleibt aktiv. Authenticator verloren? Zusätzlich --reset-mfa angeben.")
        print("Bestehende Sitzungen bleiben gültig -- zum Aussperren zusätzlich das Volume neu anlegen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
