# 2 · Seiten-Forensik (Page forensics)

Stand: 2026-11-20. Grundlage: Code-Lesung (`frontend/src/pages/*`, `App.tsx`, `index.css`).
Ohne Nutzungsdaten (siehe `1-usage-audit.md`) sind das **strukturelle** Befunde. Jeder Punkt
nennt die Stelle im Code und den Fix. **Fett** = Datenverlust oder gefährliche Aktion, kommt
zuerst dran.

Querschnitt (alle Seiten):

- **Q1 Seitenkopf doppelt sich mit dem Menü.** Jede Seite hat `.page-header` mit `<h1>` plus
  Erklärabsatz; der Menüpunkt sagt dasselbe. Fix: Titel in die Top-Bar, Erklärtext nur im leeren
  Zustand oder hinter „ⓘ“.
- **Q2 Spinner statt Skeleton** auf jeder Seite (`<span className="spinner" />`). Fix: Skeleton
  pro Layout.
- **Q3 Handy-Navigation.** Unter 860 px wird die Sidebar zu 11 umbrechenden Pillen über dem
  Inhalt (`index.css` `@media (max-width: 860px)`); Abmelden wird ausgeblendet. Fix: untere
  Tab-Leiste (4 Bereiche + Mehr), Safe-Area-Insets, Abmelden unter Mehr.
- **Q4 Alle Bestätigungen sind `window.confirm`** (11 Stellen), kein Undo, kein Papierkorb.
  Fix: Prüfdialog mit Klartext, was passiert; wo das Backend es erlaubt, Undo-Toast.
- **Q5 Keine globale Suche.** ⌘K gibt es heute **nicht** – „Search must find everything it found
  before“ heißt hier: die Inventar-Suche (Name, Hostname, IP, MAC, Hersteller, Modell, Standort,
  Zweck) muss erhalten bleiben. Eine ⌘K-Suche wäre neu (Geräte + Doku-Kapitel + Seiten).
- **Q6 Emoji-Icons in der Nav** (🏠🖧🗺️…) rendern je Plattform anders; `lucide-react` ist schon
  Abhängigkeit. Fix: Lucide-Icons.

## Übersicht `/` (DashboardPage.tsx)

1. **Zahl doppelt:** Untertitel „N Geräte dokumentiert, davon M gerade erreichbar“ *und* Kacheln
   „Geräte insgesamt“ / „gerade erreichbar“ zeigen dieselben zwei Zahlen. Fix: eine ruhige Zeile.
2. Vier gleich laute Stat-Kacheln; die wichtige Frage („ist etwas ausgefallen?“) hat keine
   Hervorhebung. `counts.offline` (inzwischen entfernt, #85) wird geliefert, aber **nirgends angezeigt**. Fix: Status-Hero
   „Alles erreichbar“ / „2 wichtige Geräte nicht erreichbar → ansehen“.
3. „Wichtigste Geräte“ ist auf 10 gekappt (`routes/overview.py` `[:10]`), die Kachel zählt alle
   kritischen. Bei 12 kritischen fehlen 2 ohne Hinweis. Fix: „+2 weitere“ verlinkt auf
   `/geraete?importance=critical`.
4. Ergebnis von „Internet prüfen“ verschwindet beim Verlassen der Seite. Fix: letzte Prüfung mit
   Zeitstempel anzeigen (oder im URL-State halten).
5. `recentlyChanged` (inzwischen entfernt, #85) wird geliefert, aber nicht angezeigt (versteckte Daten). Fix: „Zuletzt
   geändert“ als einklappbare Liste oder bewusst aus der API nehmen.
6. LLM-Hinweis ist ein Absatz. Fix: Status-Chip „Assistent nicht eingerichtet · Einrichten“.

## Geräte `/geraete` (InventoryPage.tsx)

1. **Mehrfach-Löschen** („Ausgewählte löschen“) nur mit `confirm`, endgültig, kein Undo; liegt
   rechts neben „Zusammenführen“. Fix: Prüfschritt mit Namensliste; Löschen getrennt vom Merge.
2. **Suchtext und Sortierung gehen bei Zurück verloren** (`query`, `sort` sind `useState`, nur
   `kind`/`parentId`/`project` stehen in der URL). Typischer Weg: suchen → Gerät öffnen → Zurück
   → Suche weg. Fix: `?q=`, `?sort=`.
3. Eingeklappte Compose-Gruppen (`collapsed`) gehen ebenfalls verloren. Fix: URL oder
   `sessionStorage`.
4. Duplikat-Hinweis steht als großer Block **über** der Liste und schiebt sie auf dem Handy aus
   dem Bild. Fix: Chip „3 mögliche Duplikate“ → eigene Prüfansicht.
5. Tabelle mit 5–6 Spalten auf dem Handy nur horizontal scrollbar. Fix: Zeilen als Listeneinträge
   (Name, IP · Art, Status-Chip) unter 640 px.
6. Spaltenköpfe sind klickbar (Sortierung), sehen aber nicht so aus; dritter Klick setzt die
   Sortierung unsichtbar zurück. Fix: sichtbares Sortier-Menü. Später korrigiert (Issue #75): Das
   Menü bleibt, die Köpfe sind aber wieder klickbar und zeigen ▲/▼ und `aria-sort`, womit der
   Kritikpunkt „unsichtbares Zurücksetzen“ entfällt.
7. „+ Gerät anlegen“ fragt den Namen per `window.prompt` ab (auf Handys hässlich, teils blockiert)
   und bleibt danach in der Liste statt das neue Gerät zu öffnen. Fix: Sheet mit Name + Art, danach
   direkt auf `/geraete/:id?edit=1`.

## Gerät `/geraete/:id` (SystemDetailPage.tsx, 1185 Zeilen)

1. **„Löschen“ steht als rote Taste direkt neben „Bearbeiten“** im Kopf; löscht Gerät *und*
   zugehörige Zugänge. Fix: unter „⋯ Mehr“, Prüfschritt mit Liste der mitgelöschten Zugänge.
2. **Neustart / Container stoppen / Shelly / HA-Schalter** sind Ein-Klick-Tasten mitten im Inhalt.
   Fix: eigener Tab „Steuern“, jede Aktion mit Bestätigung, Zustand sichtbar vor dem Klick.
3. **Bearbeiten-Modus:** Zurück / Seitenwechsel verwirft den Entwurf ohne Nachfrage. Fix:
   Ungespeichert-Warnung (`useBlocker`) und Entwurf in `sessionStorage`.
4. Bis zu 10 Badges im Kopf, darunter **ein Badge, das eine Taste ist** („⚠ n Fehler“) und Links,
   die wie Badges aussehen („Weboberfläche ↗“). Fix: Summary-Strip (Status · Wichtigkeit · IP ·
   zuletzt gesehen · Quelle) + eine Linkzeile.
5. 15 `<h2>`-Abschnitte untereinander (Beschreibung, Technische Daten, Verbrauchsmaterial,
   Container, Schalten, Direkt ausgelesen, Fehlerprotokoll, Konfigurationsverlauf,
   Dienste, Zugänge, Konsole …). Fix: Tabs `Überblick · Technik · Verlauf · Zugänge · Steuern`
   mit `?tab=` in der URL; nur „Überblick“ trägt die Zusammenfassung.
6. `MergePanel` ist immer offen für Admins, auch wenn es keinen Kandidaten gibt. Fix: nur als Chip,
   wenn Kandidaten existieren.
7. Nach Zusammenführen `window.location.reload()` – verliert Scrollposition und Zustand. Fix:
   Navigieren auf das behaltene Gerät.
8. Klartext-Secret (`secrets`-State) bleibt nach Anzeige sichtbar, bis man die Seite verlässt.
   Fix: nach 30 s automatisch wieder verbergen (Sicherheitsabschnitt README beachten).

## Dokumentation `/dokumentation/:slug` (DocsPage.tsx)

1. **Stiller Datenverlust:** Kapitelwechsel während „Bearbeiten“ setzt `editing=false` und
   verwirft den Entwurf (`useEffect([slug])`). Gleiches für die „Eigene Notizen“-Bearbeitung
   (`manualDraft`). Fix: Warnung + Entwurf in `sessionStorage` je Slug.
2. **„Alles neu erzeugen“** liegt im Seitenkopf als normale Taste. Laut `docs.py` bleiben manuelle
   Seiten erhalten, aber der Klick ist teuer (LLM). Fix: unter „⋯“, mit Erklärung.
3. „Neu erzeugen“ einer Seite überschreibt die Handbearbeitung (nur `confirm`). Verlauf existiert
   (gut) – Fix: nach dem Reset Undo-Toast „Wiederherstellen“ (nutzt `restoreDocVersion`).
4. Kapitelliste ist eine Karte links mit 260 px; auf dem Handy steht sie **über** dem Text,
   12 Einträge lang. Fix: Kapitelwahl als Dropdown/Sheet in der Top-Bar.
5. Notfall-Kapitel ist nur im Leerzustand hervorgehoben. Fix: immer erster Eintrag, rot markiert.

## KI-Assistent `/assistent` (ChatPage.tsx)

1. Gewählte Unterhaltung (`chatId`) steht nicht in der URL – Zurück oder Neuladen landet in einer
   anderen. Fix: `/assistent/:chatId`.
2. Auf dem Handy ist die Eingabezeile **nicht fixiert** (CSS-Kommentar: Fallback auf normales
   Scrollen, weil die gestapelte Sidebar Platz frisst). Fix: mit unterer Tab-Leiste `100dvh`-Layout,
   Eingabe über der Tastatur (`visualViewport`).
3. Unterhaltungswahl als `<select>` im Seitenkopf. Fix: Verlauf als Sheet.
4. Eingabetext geht beim Seitenwechsel verloren. Fix: Entwurf je Chat in `sessionStorage`.

## Netzplan & Diagnose `/plan` (PlanPage.tsx)

1. Erklärtext zur Layer-3-Ansicht ist ein ~120-Wörter-Absatz über dem Plan. Fix: „ⓘ Wie lese ich
   den Plan?“.
2. Ansicht (Physisch/Layer 3) nicht in der URL. Fix: `?view=layer3`.
3. Die Ausfall-Meldung oben **und** die Überwachungsliste nennen dieselben Geräte. Fix: nur
   Statuszeile, Liste darunter.
4. Speedtest und DNS-Test hängen unten an einer Plan-Seite. Fix: Diagnose als eigener Tab.
5. SVG-Plan auf dem Handy nur seitlich scrollbar, Klickziele klein. Fix: Pinch-Zoom-Container,
   Tippen öffnet Gerät.

## Zugänge `/zugaenge` (AccountsPage.tsx, admin)

1. **Löschen** mit `confirm` („Passwort geht verloren“), kein Undo. Fix: Prüfschritt; besser
   Archivieren, wenn das Backend es bekommt (Backend-Änderung → eigenes Ticket, `risk:high`).
2. Großer Hinweiskasten („kein Passwort-Manager“) dauerhaft oben. Fix: einmal zeigen, dann „ⓘ“.
3. Formular „Neuer Zugang“ ersetzt die Liste; Zurück verlässt die Seite und verwirft das Formular.
   Fix: `/zugaenge/neu` bzw. `/zugaenge/:id` als eigene Route.

## Einstellungen `/einstellungen` (SettingsPage.tsx)

1. Tab ist `useState` – Zurück landet immer auf „Allgemein“. Fix: `?tab=llm`.
2. Sieben Tabs als Tastenreihe, auf dem Handy umbrechend. Fix: Liste → Unterseite.
3. Ungespeicherte Formularänderungen gehen beim Tabwechsel ohne Warnung verloren (prüfen beim Bau).
4. „Token widerrufen“ ist eine rote Taste in der Liste. Fix: Prüfschritt bleibt, Taste unter „⋯“.

## Seltene Seiten (Scan, Benutzer, Protokoll, Netze & WLAN)

- Scan: Fortschritt pollt nur bei sichtbarer Seite – gut. Ergebnis ohne „Was ist neu?“-Zeile.
- Benutzer: „Löschen“ und „MFA zurücksetzen“ nebeneinander als Tasten. → „⋯“ + Prüfschritt.
- Protokoll: Filter (Aktion, nur Fehler) nicht in der URL.
- Netze & WLAN: Leerzustand erklärt nicht, dass ein Controller-Zugang nötig ist.

## Onboarding (Login → MFA → Einrichtung)

- Reihenfolge ist im Frontend (`App.tsx`) und Backend (`deps.current_user`) erzwungen – gut, die
  Regel „nur Onboarding, bis es fertig ist“ ist schon erfüllt. Mitglieder werden nicht
  eingesperrt (bewusst). Die MFA-Seite hat einen Abmelden-Ausweg (geprüft, `MfaEnrollPage.tsx:106`).
  Die Einrichtung (`SetupPage.tsx`) hat **keinen** – wer dort abbrechen will, kommt nur über das
  Schließen des Tabs raus. Fix: „Später einrichten / Abmelden“ ergänzen.
