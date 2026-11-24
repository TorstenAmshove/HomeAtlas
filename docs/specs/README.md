# HomeAtlas-Spezifikation (Ist-Verhalten)

Diese Specs beschreiben, **was HomeAtlas heute tut**, aus dem Code zurückgewonnen (Stand Commit
`0159807`). Sie haben zwei Aufgaben:

1. **Überblick**: Die Funktionslandkarte unten zeigt jede Fähigkeit mit Rolle, Seite und API.
2. **Grundlage für Spec-Driven Development**: Die Specs lassen sich anpassen und einem
   Coding-Agenten übergeben, etwa um eine Alternative zu bauen, auch mit anderer Technik.

Methode: Format der Fähigkeits-Specs nach OpenSpec (Requirements mit `MUSS`/`SOLL` und Szenarien
`WENN … DANN`), übergreifende Regeln als „Constitution“ nach Spec Kit, Verträge (API, Datenmodell,
KI-Werkzeuge) maschinell aus dem Code erzeugt. Jede Anforderung nennt ihre Quelle (`datei:zeile`).
Hintergrund: [docs/ai-workflow/methoden-und-skills.md](../ai-workflow/methoden-und-skills.md),
Abschnitt 11.

## Aufbau

| Datei | Inhalt |
|---|---|
| [constitution.md](constitution.md) | übergreifende Prinzipien (Sicherheit, Rollen, Lesen/Schreiben, KI-Grenze, Betrieb) |
| [glossary.md](glossary.md) | Fachbegriffe |
| [capabilities/](capabilities/) | eine `spec.md` je Fähigkeit, Vorlage: [_template.md](capabilities/_template.md) |
| [contracts/openapi.json](contracts/openapi.json) | REST-API, aus FastAPI erzeugt |
| [contracts/data-model.md](contracts/data-model.md) | Entitäten und Felder |
| [contracts/llm-tools.md](contracts/llm-tools.md) | Werkzeuge des KI-Assistenten und des MCP-Endpunkts, vollständig in [llm-tools.json](contracts/llm-tools.json) |
| [contracts/catalogs.json](contracts/catalogs.json) | feste Kataloge: 55 Ports, Port-Hinweise, 41 Hersteller-Doku-Links, OUI-Fallback, verbotene Passwörter, Wortliste Erstpasswort |
| [traceability.md](traceability.md) | Abdeckung: jede Route, Tabelle, jedes Werkzeug und jede Seite → Spec (erzeugt) |
| [offene-punkte.md](offene-punkte.md) | alle `OFFEN`-Punkte gesammelt: vor einer Alternative entscheiden |

### Markierungen

- **[Muss]**: fachlich oder sicherheitsrelevant, gilt auch für eine Alternative.
- **[Impl]**: Eigenart der heutigen Umsetzung, darf ersetzt werden.
- **OFFEN**: Unklarheit, Widerspruch oder Verhalten, das eher nach Bug als nach Absicht aussieht.

## Funktionslandkarte

| Fähigkeit | Worum es geht | Rolle | Seite (Route) | API |
|---|---|---|---|---|
| [auth-und-rollen](capabilities/auth-und-rollen/spec.md) | Anmeldung, Pflicht-2FA (TOTP), Passwortrichtlinie, Benutzer, Rollen, Zugriffsprotokoll | alle / Benutzer und Protokoll: ADMIN | Login, MFA-Einrichtung, Benutzer (`/benutzer`), Protokoll (`/protokoll`) | `/api/auth/*`, `/api/users*`, `/api/access-log` |
| [setup-wizard](capabilities/setup-wizard/spec.md) | Ersteinrichtung nach dem ersten Login | ADMIN | Setup | `/api/setup`, `/api/health` |
| [dashboard](capabilities/dashboard/spec.md) | Übersicht: Zustand von Netz und Geräten | alle | Übersicht (`/`) | `/api/dashboard` |
| [discovery-und-scan](capabilities/discovery-und-scan/spec.md) | Netz scannen aus mehreren Quellen, Namensregeln, Zeitplan | ADMIN | Netzwerk-Scan (`/scan`) | `/api/scans*`, `/api/settings/oui/refresh` |
| [klassifikation-llm](capabilities/klassifikation-llm/spec.md) | unsichere Geräte per LLM einordnen, Hersteller-Doku-Links | – (im Scan) | – | – |
| [inventar](capabilities/inventar/spec.md) | Geräte ansehen, bearbeiten, Duplikate zusammenführen, Konfigurationsversionen | alle lesen / ADMIN ändern | Geräte (`/geraete`, `/geraete/:id`) | `/api/systems*` |
| [credentialed-probing](capabilities/credentialed-probing/spec.md) | Geräte mit freigegebenen Zugängen streng lesend auslesen (SSH, HTTP, TR-064, UniFi, Proxmox, Docker) | ADMIN | Gerätedetail | `/api/systems/{id}/probe` |
| [zugangsdaten](capabilities/zugangsdaten/spec.md) | Zugänge verschlüsselt speichern, einzeln anzeigen, zuordnen | ADMIN | Zugänge (`/zugaenge`) | `/api/accounts*` |
| [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) | Netze/VLANs, WLANs, WANs aus Controllern | alle lesen / ADMIN ändern | Netze & WLAN (`/netze`) | `/api/network-resources*` |
| [topologie](capabilities/topologie/spec.md) | automatischer Netzplan für Laien, Layer-3-Ansicht | alle | Netzplan (`/plan`) | `/api/topology*.svg` |
| [dokumentation](capabilities/dokumentation/spec.md) | 13 Kapitel aus dem Inventar, manuelle Notizen, Override, Versionen | alle lesen / ADMIN ändern | Dokumentation (`/dokumentation`) | `/api/docs*` |
| [erreichbarkeit](capabilities/erreichbarkeit/spec.md) | Ketten „Internet → Weg → Inventar“, Pfadstatus aktiv/verwaist/unklar | alle lesen | Kapitel in der Dokumentation | – |
| [monitoring](capabilities/monitoring/spec.md) | wichtige Geräte laufend prüfen, Ausfallverlauf | alle | Übersicht, Gerätedetail | `/api/monitor*` |
| [diagnose](capabilities/diagnose/spec.md) | Live-Messungen: Ping, Port, DNS, HTTP, Traceroute, Speedtest | siehe Spec | Gerätedetail, Assistent | `/api/diagnostics*` |
| [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) | KI-Assistent mit Werkzeugen, externer MCP-Endpunkt | alle / MCP-Tokens: ADMIN | KI-Assistent (`/assistent`) | `/api/chats*`, `/api/mcp`, `/api/settings/mcp-tokens*` |
| [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md) | Einstellungen, LLM-Anbieter und Modelle | alle sehen / ADMIN ändern | Einstellungen (`/einstellungen`) | `/api/settings*` |

Die genauen Rechte je Route stehen in der jeweiligen Spec. Bei Abweichungen gilt die Spec.

## Quellverweise und Code-Struktur

Die Quellverweise `datei:zeile` beziehen sich auf den Stand der Rückgewinnung (Commit `0159807`).
Seitdem sind die Routen aus `backend/app/main.py` auf Module je Fähigkeitsgruppe verteilt; die
Funktionsnamen sind gleich geblieben, also im Zweifel nach dem Namen suchen:

| Routen-Modul (`backend/app/routes/`) | Fähigkeiten |
|---|---|
| `auth.py` | auth-und-rollen (Login, MFA, Passwort, Benutzer), `/api/health` aus setup-wizard |
| `settings.py` | einstellungen-und-llm-provider, MCP-Tokens aus assistent-chat-und-mcp |
| `systems.py` | inventar, Auslesen eines Geräts aus credentialed-probing |
| `accounts.py` | zugangsdaten |
| `docs.py` | dokumentation |
| `scans.py` | discovery-und-scan |
| `diagnostics.py` | diagnose |
| `chat.py` | assistent-chat-und-mcp |
| `overview.py` | dashboard, setup-wizard, monitoring, topologie, Zugriffsprotokoll |

Gemeinsame Abhängigkeiten (`current_user`, `require_admin`, WebSocket-Prüfung) liegen in
`backend/app/deps.py`.

## Specs pflegen

- Ändert sich das Verhalten, zuerst die Spec anpassen, dann den Code (Spec-Driven Development, siehe
  [docs/ai-workflow/](../ai-workflow/README.md)).
- Specs und ADRs teilen sich die Arbeit: Die Specs beschreiben, **was** HomeAtlas heute tut, und
  werden mit jeder Verhaltensänderung aktualisiert. Die [ADRs](../adr/README.md) halten fest,
  **warum** eine übergreifende Entscheidung so gefallen ist, und werden nie geändert, nur ersetzt.
  Eine Constitution-Regel mit ADR-Link ändert sich daher nur über ein neues ADR; die Begründung
  wird nicht in die Constitution kopiert.
- Verträge neu erzeugen und Abdeckung prüfen (aus dem Repo-Wurzelverzeichnis):

```bash
python docs/specs/export_contracts.py   # openapi.json, llm-tools.json, catalogs.json (braucht backend/requirements.txt)
python docs/specs/trace_specs.py        # traceability.md + Liste in offene-punkte.md, Exit 1 bei Lücken
```

## An einen Coding-Agenten übergeben (Alternative bauen)

1. **Entscheiden**: [offene-punkte.md](offene-punkte.md) durchgehen. Für jede Fähigkeit festlegen:
   übernehmen, ändern oder weglassen. Änderungen direkt in die Spec schreiben, gern als
   OpenSpec-Delta (`## ADDED`, `## MODIFIED`, `## REMOVED Requirements`).
2. **Technik festlegen**: Die [Impl]-Regeln in der Constitution ersetzen oder bestätigen.
3. **Paket für den Agenten**: `constitution.md`, `glossary.md`, die gewünschten
   `capabilities/*/spec.md`, `contracts/`. Den Abschnitt „Ist-Implementierung“ nur mitgeben, wenn
   die Technik gleich bleibt.
   Nicht in den Specs stehen die festen Texte: Systemprompts von Chat, Klassifikation und Doku
   (`backend/app/prompts.py`), Kapitel-Einleitungen und Notfall-Checkliste (`backend/app/docs.py`).
   Entweder als Anhang mitgeben oder dem Agenten ausdrücklich zur Neuformulierung freigeben.
4. **Reihenfolge** (Abhängigkeiten): auth-und-rollen → setup-wizard → einstellungen-und-llm-provider
   → inventar → discovery-und-scan → zugangsdaten → credentialed-probing → netzwerkressourcen-vlans
   → dokumentation → topologie → dashboard → monitoring → diagnose → assistent-chat-und-mcp →
   klassifikation-llm.
5. **Je Fähigkeit** den Agenten erst einen Plan schreiben lassen (Spec Kit: specify → plan → tasks),
   der jedem Szenario einen Test zuordnet, dann umsetzen. Fertig ist eine Fähigkeit, wenn alle
   Szenarien als Tests grün sind.
6. **Abnahme**: Soll die Alternative API-kompatibel sein, dienen `contracts/openapi.json` und der
   Browser-Smoke-Test (`frontend/e2e/`) als Black-Box-Prüfung.
