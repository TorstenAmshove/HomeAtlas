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
| **Zugänge** | – | `/zugaenge` | nur Admin |
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

Fortschritt: **3 von 15 Oberflächen** (12 Seiten + 3 Gates): Start (PR 2), Dokumentation und Assistent (PR 5, Hilfe). Shell gebaut (PR 1): Schalter, Tokens,
Dunkelmodus, `frontend/src/shell/` (AppShell, ⌘K), Bausteine `components/Skeleton.tsx`,
`components/ConfirmDialog.tsx`, `lib/useUndoToast.tsx`, `lib/useUrlState.ts`. Die Seiten zeigen in der
neuen Shell vorerst noch ihren eigenen Seitenkopf; den nimmt jeweils der PR ihres Bereichs heraus.

- **Start** (PR 2, `pages/start/StartCalm.tsx`): Status-Hero aus `/api/monitor` (dieselbe Menge wie
  der Netzplan, B3), eine ruhige Zahlenzeile statt Untertitel + Kacheln, „+N weitere“ bei mehr als 10
  kritischen Geräten (B1, verlinkt vorerst auf `/geraete`, bis die Liste `?importance=` kann),
  „Stand letzter Scan“ für nicht überwachte kritische Geräte (B2), Ergebnis von „Internet prüfen“ mit
  Uhrzeit, Status-Chip statt KI-Absatz, Skeleton, kein Seitentitel. `recentlyChanged` bleibt bewusst
  ungenutzt. Bei ausgeschaltetem Schalter rendert `/` unverändert `DashboardPage.tsx`.
- **Hilfe** (PR 5): Dokumentation ohne Seitenkopf, Kapitelliste links (Handy: Auswahl oben), Notfall immer
  zuerst und markiert, Kapitelkopf „Stand · automatisch erzeugt/von Hand bearbeitet · eigene Notiz“,
  Verlauf in `?versions=1`, „Neu erzeugen“/„Alles neu erzeugen“ unter „⋯“ mit Prüfdialog, nach „Neu
  erzeugen“ Rückgängig über die gesicherte Version. Assistent mit Route `/assistent/:chatId`,
  Unterhaltung als Auswahl oben, Eingabe auf dem Handy über der unteren Leiste und der Tastatur
  (`visualViewport`), Hinweis, wenn kein KI-Anbieter eingerichtet ist. Entwürfe (Doku-Text, Notizen,
  Chat-Eingabe) liegen in beiden Oberflächen im `sessionStorage`; Kapitelwechsel mit ungespeicherten
  Änderungen fragt nach (`lib/useLeaveGuard.tsx`, ohne Data-Router kein `useBlocker`).
