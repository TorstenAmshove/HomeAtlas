# 4 · Routen- und Aktionskarte (Nothing may disappear)

Stand: 2026-11-20. Quelle: `frontend/src/App.tsx` (Routen, `NAV`) und alle Seiten. Jede Zeile
braucht im neuen Menü ein Zuhause; Phase 3 macht daraus `nav.config.ts` plus einen Test, der
fehlschlägt, wenn eine Route hier steht, aber keinem Bereich zugeordnet ist.

## Gates (keine Routen, laufen vor der App)

| Gate | Datei | Bedingung | Aktionen |
|---|---|---|---|
| Login | `LoginPage.tsx` | keine Sitzung | Anmelden |
| MFA-Einrichtung | `MfaEnrollPage.tsx` | `!user.totpEnabled` (Backend erzwingt) | Einrichtung starten, Aktivieren, Abmelden |
| Einrichtungsassistent | `SetupPage.tsx` | `!setupCompleted && isAdmin` | Weiter, Zurück, Gerät/Konto hinzufügen/entfernen, Fertig |

## Routen

Vorgeschlagener Bereich = Vorschlag für Phase 3 (Mockup-Shell nutzt ihn schon).

| Route | Seite | Rolle | Vorgeschlagener Bereich → Tab | Aktionen heute (alle bleiben) |
|---|---|---|---|---|
| `/` | DashboardPage | alle | **Start** | Internet prüfen · Netzwerk scannen (admin) · Link je Art → `/geraete?kind=` · Link je kritischem Gerät · Link Einstellungen |
| `/geraete` | InventoryPage | alle | **Geräte → Liste** | Suche · Filter Art (`?kind`) · Filter Compose (`?project`) · Filter Host (`?parentId`) · Sortieren je Spalte · Compose-Gruppe ein/aus · Gerät anlegen (admin) · Auswahl/Alle (admin) · Ausgewählte löschen (admin) · 2 zusammenführen (admin) · Duplikat: behalte A/B, kein Duplikat (admin) |
| `/geraete/:id` | SystemDetailPage | alle (Aktionen admin) | **Geräte → (Detail)** | Bearbeiten/Speichern/Abbrechen · Löschen · Gerät auslesen · Gerät neu starten · Zusammenführen (MergePanel) · Fehlerprotokoll · Konfigurationsverlauf ansehen · Secret anzeigen · SSH-Schlüssel erzeugen · SSH-Konsole · Docker: Starten/Stoppen/Neu starten/Logs/Live-Logs/Konsole · Remote-Container & Proxmox-Gäste: Starten/Stoppen/Neu starten/Logs/System-Logs/Aufgabenprotokoll/Konsole/noVNC · Shelly Ein/Aus · HA-Entity Ein/Aus · Links: Weboberfläche, Hersteller-Doku, eigene Doku |
| `/plan` | PlanPage | alle | **Geräte → Netzplan** (+ **Start**-Status) | Physisch / Layer 3 · Gerät im Plan antippen · DNS testen · Jetzt prüfen (admin) · Speedtest |
| `/netze` | NetworksPage | alle | **Geräte → Netze & WLAN** | Bearbeiten/Speichern je Netz (admin) |
| `/dokumentation` | DocsPage | alle | **Hilfe → Dokumentation** | Kapitel wählen · Zur Notfall-Checkliste · Alles neu erzeugen (admin) |
| `/dokumentation/:slug` | DocsPage | alle | **Hilfe → Dokumentation** | Bearbeiten/Speichern · Notiz hinzufügen/bearbeiten · Verlauf · Ansehen · Wiederherstellen · Zurück zum aktuellen Stand · Neu erzeugen (admin) |
| `/assistent` | ChatPage | alle | **Hilfe → Assistent** | Senden · Spracheingabe · Vorschlag antippen · Unterhaltung wählen · Neue Unterhaltung |
| `/zugaenge` | AccountsPage | **admin** | **Zugänge** | Neuer Zugang · Bearbeiten · Speichern · Löschen · Anzeigen (Secret) · Zuordnung hinzufügen/entfernen · SSH-Schlüssel erzeugen · Schlüssel verteilen |
| `/scan` | ScanPage | **admin** | **Mehr → Scan** | Scan starten · frühere Scans · Log |
| `/benutzer` | UsersPage | **admin** | **Mehr → Benutzer** | Anlegen · Bearbeiten · Löschen · MFA zurücksetzen |
| `/protokoll` | AccessLogPage | **admin** | **Mehr → Protokoll** | Filter Aktion · nur Fehler · Aktualisieren |
| `/einstellungen` | SettingsPage | alle (Tabs je Rolle) | **Mehr → Einstellungen** | Tabs Allgemein · KI-Assistent (Modelle laden, Verbindung testen) · Netzwerk-Scan (Hersteller-DB aktualisieren, Standard-Zugang) · Überwachung · MCP-Server (Token erzeugen/widerrufen) · Konto (Passwort ändern) · Über |
| `*` | → `/` | alle | – | Redirect |
| (Sidebar) | App.tsx | alle | **Mehr → Konto** | Abmelden · Anzeige „Angemeldet als …“ |

## URL-Parameter, die heute schon gelten (müssen weiter funktionieren)

`/geraete?kind=`, `/geraete?parentId=`, `/geraete?project=`, `/dokumentation/:slug`. Externe Links
dahin gibt es aus: Übersicht (Art), Netzplan-SVG (Gerät/Host), Doku-Markdown (Geräte-Links).

## Suche

Heute: **nur** die Inventar-Suche (Felder Name, Hostname, IP, MAC, Hersteller, Modell, Standort,
Zweck; clientseitig). Eine ⌘K-Suche existiert nicht. Die neue ⌘K-Suche muss mindestens diese
Felder abdecken, plus Seiten und Doku-Kapitel; die Inventar-Suche bleibt in der Liste.

## Zählung für die Checkliste in Phase 4

12 Routen-Seiten + 3 Gates = **15 Oberflächen**. (Die Vorlage spricht von 49 Seiten – HomeAtlas
hat 15.) Plus die Shell (Sidebar/Top-Bar/Bottom-Bar).
