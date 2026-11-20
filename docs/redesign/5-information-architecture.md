# 5 · Informationsarchitektur (Phase 3)

Stand: 2026-11-20 · Richtung **B (reduziert) mit Dunkelmodus** ist gewählt.

## Bereiche

Eine Datei steuert das ganze Menü: [`frontend/src/nav/config.ts`](../../frontend/src/nav/config.ts).
Sidebar (Desktop) und untere Leiste (Handy) zeigen die Bereiche; der aktive Bereich legt seine Tabs
in die Top-Bar.

| Bereich | Tabs in der Top-Bar | Routen | Wer sieht es |
|---|---|---|---|
| **Start** | – | `/` | alle |
| **Geräte** | Liste · Netzplan · Netze & WLAN | `/geraete`, `/geraete/:id`, `/plan`, `/netze` | alle |
| **Hilfe** | Dokumentation · Assistent | `/dokumentation`, `/dokumentation/:slug`, `/assistent` | alle |
| **Zugänge** | – | `/zugaenge`, `/zugaenge/neu`, `/zugaenge/:id` | nur Admin |
| **Mehr** | Scan · Benutzer · Protokoll · Einstellungen | `/scan`, `/benutzer`, `/protokoll`, `/einstellungen` | Admin alle Tabs, Mitglied nur Einstellungen |

Mitglieder sehen 4 Bereiche, Admins 5; beides passt in eine Handy-Leiste ohne „Mehr“-Überlauf.
„Abmelden“ und „Angemeldet als …“ wandern unter **Mehr** (heute auf dem Handy unsichtbar).

Detailseiten (`/geraete/:id`) markieren den Tab ihrer Liste; auf dem Handy ersetzt dort ein
„← Geräte“ die Tab-Reihe, damit nicht zwei Tab-Reihen übereinander stehen. Routen, die nur zwischen
Geschwistern im selben Tab wechseln (`/dokumentation/:slug`, `/assistent/:chatId`, in `ROUTES` als
`sibling: true` markiert), behalten die Tab-Reihe; dort wählt man Kapitel bzw. Unterhaltung auf der
Seite selbst.

## Kein verwaister Pfad

`npm run build` führt `scripts/check-nav.ts` aus (also auch CI und das Docker-Image). Es schlägt fehl,
wenn eine `<Route>` in `App.tsx` keinen Eintrag in `ROUTES` hat, ein Menüeintrag ins Leere zeigt, eine
der 13 Routen von vor der Umgestaltung (`LEGACY_ROUTES`) weder existiert noch umgeleitet wird, oder
Admin-Markierungen von Tab und Route auseinanderlaufen. Getestet: eine zusätzliche Route ohne
Menüeintrag lässt den Build scheitern.

## Zustand in der URL (Zurück landet, wo man war)

| Seite | Parameter |
|---|---|
| Geräte | `q` (Suche), `kind`, `project`, `parentId` (wie bisher), `status`, `importance`, `sort` |
| Gerät | `tab` (`ueberblick` · `technik` · `verlauf` · `zugaenge` · `steuern`), `edit=1` |
| Netzplan | `view` (`physisch` · `layer3`) |
| Dokumentation | Kapitel im Pfad (wie bisher), `versions=1` |
| Assistent | neue Route `/assistent/:chatId` (`/assistent` bleibt) |
| Zugänge | neue Routen `/zugaenge/neu`, `/zugaenge/:id` (statt Formular im Seitenzustand) |
| Einstellungen | `tab` |
| Protokoll | `action`, `failures=1` |

Ungespeicherte Entwürfe (Doku-Text, Notizen, Geräte-Formular, Chat-Eingabe) liegen zusätzlich in
`sessionStorage` und lösen beim Verlassen eine Rückfrage aus.

## ⌘K-Suche

Neu (eine globale Suche gab es bisher nicht). Quellen in `SEARCH_SOURCES`:

1. **Seiten** – aus `ROUTES`/`AREAS`, nach Rolle gefiltert.
2. **Geräte** – `GET /api/systems`, Felder `DEVICE_SEARCH_FIELDS` (Name, Hostname, IP, MAC, Hersteller,
   Modell, Standort, Zweck). Die Geräteliste nutzt seit dieser Phase **dieselbe** Funktion
   (`lib/search.ts` → `matchesDeviceQuery`), damit beide nie auseinanderlaufen.
3. **Doku-Kapitel** – Titel aus `GET /api/docs`.

Auf dem Handy öffnet die Lupe in der Kopfzeile dieselbe Suche als Vollbild.

## Schalter (Feature-Flag)

- Einstellung `uiCalm` (Standard **aus**) in der `settings`-Tabelle, umschaltbar von Admins unter
  *Einstellungen → Allgemein → „Neue Oberfläche“*. Zurückschalten dauert einen Klick.
- Ausgeliefert über `GET /api/health` (wie `setupCompleted`), damit die Oberfläche vor dem ersten
  Seitenaufbau weiß, welche Shell sie zeigt.
- Pro Browser übersteuerbar: `?ui=calm` bzw. `?ui=classic` merkt sich die Wahl in `localStorage`.
  So lässt sich die neue Oberfläche auf dem eigenen Handy testen, ohne sie für alle einzuschalten.
- **Staging:** es gibt keine Staging-Instanz. Ersatz: eine Test-Instanz mit
  `HOMEATLAS_UI_CALM_DEFAULT=1` (gilt nur, solange `uiCalm` nie gesetzt wurde) oder die
  Browser-Übersteuerung oben auf der echten Instanz.
- Alte und neue Shell rendern **dieselben Seiten-Komponenten**, solange ein Bereich noch nicht
  umgebaut ist. Umgebaute Seiten prüfen den Schalter selbst und fallen sonst auf die alte Fassung
  zurück, bis der Schalter überall an ist und die alte Fassung entfernt wird.

## Design-Tokens und Dunkelmodus

Palette aus dem Mockup (`mockups/index.html`), als CSS-Variablen unter `body:has(.app-shell)`, damit
die alte Oberfläche (ohne `.app-shell`) unverändert bleibt:

| Token | Hell | Dunkel |
|---|---|---|
| Grund | `#fafaf9` | `#161615` |
| Fläche | `#ffffff` | `#1e1e1c` |
| Text | `#1c1917` | `#ecebe8` |
| gedämpft | `#6f6a64` | `#9a968e` |
| Linie | `#e7e5e4` | `#2e2d2a` |
| Akzent | `#2f6fdb` | `#8ab4ff` |
| ok / Fehler / Warnung | `#15803d` / `#b91c1c` / `#a16207` | `#4ade80` / `#f87171` / `#fbbf24` |

Standard „wie das System“ (`prefers-color-scheme`), wählbar unter *Mehr → Einstellungen →
Darstellung* (System · Hell · Dunkel, pro Browser). `theme-color` im Manifest/`<meta>` folgt dem Modus.

## Bauplan (Phase 4)

Ein Bereich pro PR, jeweils hinter dem Schalter:

| # | PR | Inhalt |
|---|---|---|
| 1 | Shell | Schalter, Tokens, Sidebar/Top-Bar/Handy-Leiste aus `config.ts`, ⌘K, Skeleton-Baustein, Prüfdialog + Undo-Toast als Bausteine |
| 2 | Start | Übersicht |
| 3 | Geräte | Liste, Netzplan, Netze & WLAN |
| 4 | Gerät | Detailseite (eigener PR, 1185 Zeilen) |
| 5 | Hilfe | Dokumentation, Assistent |
| 6 | Zugänge + Mehr | Zugänge, Scan, Benutzer, Protokoll, Einstellungen |
| 7 | Gates | Login, MFA, Einrichtung (Ausweg aus der Einrichtung) |

Fortschritt: **12 von 15 Oberflächen** (12 Seiten + 3 Gates): Start (PR 2), Geräte-Liste, Netzplan und Netze & WLAN
(PR 3, Geräte), Gerät (PR 4), Dokumentation und Assistent (PR 5, Hilfe), Zugänge, Scan, Benutzer, Protokoll und
Einstellungen (PR 6, Zugänge + Mehr). Shell gebaut (PR 1): Schalter, Tokens,
Dunkelmodus, `frontend/src/shell/` (AppShell, ⌘K), Bausteine `components/Skeleton.tsx`,
`components/ConfirmDialog.tsx`, `lib/useUndoToast.tsx`, `lib/useUrlState.ts`. Die Seiten zeigen in der
neuen Shell vorerst noch ihren eigenen Seitenkopf; den nimmt jeweils der PR ihres Bereichs heraus.

- **Start** (PR 2, `pages/start/StartCalm.tsx`): Status-Hero aus `/api/monitor` (dieselbe Menge wie
  der Netzplan, B3), eine ruhige Zahlenzeile statt Untertitel + Kacheln, „+N weitere“ bei mehr als 10
  kritischen Geräten (B1, verlinkt auf `/geraete?importance=critical`),
  „Stand letzter Scan“ für nicht überwachte kritische Geräte (B2), Ergebnis von „Internet prüfen“ mit
  Uhrzeit, Status-Chip statt KI-Absatz, Skeleton, kein Seitentitel. `recentlyChanged` bleibt bewusst
  ungenutzt. Bei ausgeschaltetem Schalter rendert `/` unverändert `DashboardPage.tsx`.
- **Zugänge + Mehr** (PR 6, `pages/zugaenge/`, `pages/mehr/`, ein gemeinsames `mehr.css`): Zugänge als ruhige
  Liste mit Suche in `?q=`; „Neuer Zugang“ und Bearbeiten als eigene Routen `/zugaenge/neu` und `/zugaenge/:id`
  (in `ROUTES` mit `detail: true` bzw. `:id`, also „← Zugänge“ in der Top-Bar). Der Formular-Entwurf liegt im
  `sessionStorage`, **ohne** Passwort, Token, privaten Schlüssel oder Passphrase (gespeichert wird nur, dass
  etwas eingetippt war); Rückfrage beim Verlassen. „Anzeigen“ wie auf der Geräteseite (einzeln, 30 s).
  Löschen mit Prüfdialog (Passwort weg, Gerät und Zuordnungen, die den Zugang verlieren, kein Rückgängig);
  „Auf Gerät einspielen“ ebenfalls mit Prüfdialog; „Kein Passwort-Manager“ einmal, dann hinter „ⓘ“
  (`localStorage`). Einstellungen: `?tab=` in **beiden** Oberflächen; neu: Reiterliste links, auf dem Handy
  Liste → Unterseite, Rückfrage bei ungespeicherten Änderungen (Reiterwechsel und Verlassen), Token
  widerrufen unter „⋯“ mit Prüfdialog. Benutzer: Löschen und „Zwei-Faktor zurücksetzen“ unter „⋯“ mit
  Prüfdialog, Rollen hinter „ⓘ“. Protokoll: `?action=`/`?failures=1` in **beiden** Oberflächen, Status-Chips,
  Skeleton. Scan: Zusammenfassung zuerst, Fortschritt nur bei sichtbarem Tab, „Was ist neu?“ nur aus der
  Scan-Zusammenfassung. Dazu: die neue Geräteseite wird je Gerät neu aufgebaut (`key={id}`).
- **Hilfe** (PR 5): Dokumentation ohne Seitenkopf, Kapitelliste links (Handy: Auswahl oben), Notfall immer
  zuerst und markiert, Kapitelkopf „Stand · automatisch erzeugt/von Hand bearbeitet · eigene Notiz“,
  Verlauf in `?versions=1`, „Neu erzeugen“/„Alles neu erzeugen“ unter „⋯“ mit Prüfdialog, nach „Neu
  erzeugen“ Rückgängig über die gesicherte Version. Assistent mit Route `/assistent/:chatId`,
  Unterhaltung als Auswahl oben, Eingabe auf dem Handy über der unteren Leiste und der Tastatur
  (`visualViewport`), Hinweis, wenn kein KI-Anbieter eingerichtet ist. Entwürfe (Doku-Text, Notizen,
  Chat-Eingabe) liegen in beiden Oberflächen im `sessionStorage`; Kapitelwechsel mit ungespeicherten
  Änderungen fragt nach (`lib/useLeaveGuard.tsx`, ohne Data-Router kein `useBlocker`).
- **Geräte** (PR 3, `pages/geraete/`): Liste ohne Seitenkopf mit Suche, sichtbarem Sortier-Menü und
  Filterzeile „Alle · Nicht erreichbar · Wichtig · Art ▾ · Compose ▾“ (Zahlen clientseitig aus
  `GET /api/systems` über das ganze Inventar; „Nicht erreichbar“ ist `counts.offline`, also alle
  Geräte, nicht nur die überwachten), alles in der URL (`q` und `sort` auch in der alten
  Oberfläche, dazu `status`, `importance`, `duplikate=1`). Duplikate als Chip mit Prüfansicht,
  Mehrfachauswahl erst nach „Auswählen“, Löschen mit Prüfdialog (Namen, mitgelöschte Zugänge,
  verwaiste Container), Zusammenführen getrennt davon; „+ Gerät“ als Dialog (Name, Art), danach
  die Geräteseite. Unter 640 px Listeneinträge statt Tabelle; eingeklappte Compose-Gruppen im
  `sessionStorage`. Netzplan mit `?view=layer3`, Erklärtext hinter „ⓘ“, **einer** Statuszeile aus
  `/api/monitor` (dieselbe Menge und Wortwahl wie der Start-Hero, Alarm nur bei laufender
  Überwachung), Liste „Überwachte Geräte“ (auf dem Handy vor dem Bild), Diagnose-Aktionen darunter.
  Das SVG bleibt statisch (ADR-0008/0009: kein Zoom-Bedienelement); auf dem Handy liegt es in
  doppelter Breite in einem seitlich verschiebbaren Rahmen. Netze & WLAN als ruhige Liste mit
  Leerzustand, der den nötigen UniFi-Zugang erklärt. Dazu aus der Hilfe-Prüfung: Abmelden fragt,
  wenn noch Entwürfe im Tab liegen (beide Oberflächen).
- **Gerät** (PR 4, `pages/device/DeviceCalm.tsx` + ein Baustein je Tab): Tabs in `?tab=`, Bearbeiten in
  `?edit=1`; Zusammenfassung und eine Hauptaktion nur im Überblick („Jetzt neu prüfen“ bei live
  gemeldetem Ausfall, sonst „Weboberfläche ↗“), Rest unter „⋯“. Name in der Top-Bar
  („← Geräte / NAS“, `shell/pageTitle.ts`) statt Seitentitel. „Steuern“ (nur Admin): jede
  ausschaltende Aktion mit Prüfdialog und Zustand daneben. Löschen mit Liste der mitgelöschten Zugänge
  und dem Hinweis, dass es kein Rückgängig gibt; Duplikate nur als Hinweis, wenn es Kandidaten gibt.
  Passwort verbirgt sich nach 30 s. In **beiden** Oberflächen: Formular-Entwurf im `sessionStorage`
  mit Rückfrage beim Verlassen (`lib/deviceDraft.ts`), nach dem Zusammenführen kein Neuladen der
  ganzen Seite mehr. Bei ausgeschaltetem Schalter rendert `/geraete/:id` `SystemDetailPage.tsx`.
- **Gates** (PR 7, `frontend/src/gates/`): Login, MFA-Einrichtung und Einrichtungsassistent als
  zentrierte Karte (Logo, Haushaltsname erst, wenn der Assistent ihn kennt), hell/dunkel wie die Shell,
  Tokens unter `body:has(.gate-shell)`. Login mit `autocomplete`, Passwort anzeigen/verbergen, klarer
  Fehlertext, Enter sendet. MFA in drei Schritten (App öffnen · QR scannen oder Schlüssel eingeben ·
  Code eingeben), QR weiter als Server-SVG, Schlüssel kopieren (Zwischenablage, sonst markieren),
  Abmelden immer sichtbar. Assistent mit Schrittanzeige, Entwurf im `sessionStorage` **ohne
  Passwörter** (Hinweis nach dem Neuladen, dass sie erneut einzugeben sind), Zurück/Weiter auf 44 px,
  Enter = Weiter. **Abmelden auf jedem Schritt** (mit Rückfrage, wenn schon etwas eingetragen ist), in
  **beiden** Oberflächen; kein „Überspringen“ (das Backend verlangt den Abschluss). Vor dem Login
  folgt die Wahl der Oberfläche jetzt auch der Antwort von `/api/health`, nicht nur dem zuletzt
  gesehenen Wert. Test: `frontend/e2e/gates-calm.spec.ts` (läuft nach dem Smoke-Test mit einem
  zweiten Admin, den dieser anlegt).
