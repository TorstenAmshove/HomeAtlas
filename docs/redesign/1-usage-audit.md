# 1 · Nutzungs-Audit (Usage audit)

Stand: 2026-11-20 · Phase 1 der CALM/IN-APP-Überarbeitung

## Ergebnis vorweg: es gibt keine Nutzungsdaten

HomeAtlas erhebt bewusst **keine Seitenaufrufe**. Geprüft wurde:

| Quelle | Vorhanden? | Was sie enthält |
|---|---|---|
| PostHog / Google Analytics / Plausible | nein | kein Tracking-Skript in `frontend/`, kein Eintrag in `index.html` |
| nginx-Access-Log (Frontend-Container) | nur flüchtig | stdout des Containers auf docker.lan; nicht in diesem Repo, nicht ausgewertet |
| `accessLog`-Tabelle (`backend/app/db/access_log.py`) | ja | **Sicherheits**-Ereignisse (Login, MFA, Secret-Abruf, Rollenwechsel …), max. 5000 Zeilen, keine Seitenaufrufe, keine Verweildauer, kein Gerätetyp außer User-Agent bei Login |
| Rage-/Dead-Clicks | nein | nirgends erfasst |
| Produktions-DB | nicht erreichbar | läuft auf docker.lan (ausgerollt über `ansible-docker.lan`); diese Cloud-Sitzung hat keinen Zugriff |

**Folge:** Besuche, Verweildauer, Rage-/Dead-Clicks und Handy-Anteil pro Seite lassen sich
heute nicht messen. Ich erfinde keine Zahlen.

## Ersatz-Rangfolge (Annahme, bis Daten da sind)

Die Reihenfolge unten ist eine **begründete Annahme** aus dem Code und dem Zweck der App
(Haushalts-Doku + Störungshilfe), keine Messung. Sie bestimmt vorläufig, was oben steht,
was unter „Mehr“ wandert und welche Seiten tiefe Arbeit bekommen.

| Rang | Seite | Route | Rolle | Begründung | Handy wahrscheinlich? | Platzierung |
|---|---|---|---|---|---|---|
| 1 | Übersicht | `/` | alle | Startseite nach jedem Login; zeigt „läuft alles?“ | **hoch** (schneller Blick) | Bereich *Start* |
| 2 | Geräte | `/geraete` | alle | Kerninventar, Ziel fast aller Links | mittel | Bereich *Geräte* |
| 3 | Gerät (Detail) | `/geraete/:id` | alle (Aktionen admin) | 1185 Zeilen, meiste Funktionen; Ziel aus Übersicht, Plan, Suche | mittel | Bereich *Geräte* |
| 4 | Dokumentation | `/dokumentation/:slug` | alle | Hauptprodukt laut README; Notfall-Checkliste | **hoch** im Störfall (WLAN weg → Handy) | Bereich *Hilfe* |
| 5 | KI-Assistent | `/assistent` | alle | Störungshilfe | **hoch** im Störfall | Bereich *Hilfe* |
| 6 | Netzplan & Diagnose | `/plan` | alle | Überwachung + DNS/Speedtest | mittel | Bereich *Geräte* (Tab) / Status |
| 7 | Zugänge | `/zugaenge` | admin | „schnell drankommen im Störfall“ | mittel | Bereich *Zugänge* |
| 8 | Netze & WLAN | `/netze` | alle | nur mit Controller-Daten gefüllt | niedrig | Bereich *Geräte* (Tab) |
| 9 | Netzwerk-Scan | `/scan` | admin | gelegentlich, meist geplant (`Scheduler`) | niedrig | *Mehr / Verwaltung* |
| 10 | Einstellungen | `/einstellungen` | alle (Tabs je Rolle) | selten nach Einrichtung | niedrig | *Mehr / Verwaltung* |
| 11 | Benutzer | `/benutzer` | admin | selten | niedrig | *Mehr / Verwaltung* |
| 12 | Protokoll | `/protokoll` | admin | selten, sicherheitsrelevant | niedrig | *Mehr / Verwaltung* |
| – | Login / MFA / Einrichtung | (Gate, keine Route) | – | einmalig bzw. je Sitzung | hoch | außerhalb der Navigation |

## Empfehlung: Daten erheben, ohne das Datenschutzversprechen zu brechen

Ein Drittanbieter-Tracker passt nicht zu einem selbst gehosteten Heimnetz-Tool (README
„Sicherheit“). Vorschlag für eine eigene, kleine Messung, **nur nach deiner Freigabe**:

1. Tabelle `pageViews(day, route, device[phone|desktop], role, count)` – nur Tageszähler pro
   Route-Muster (`/geraete/:id`, nicht die ID), kein User, keine IP, 90 Tage Aufbewahrung.
2. Ein `POST /api/telemetry/view` aus dem Router-Listener in `App.tsx`; abschaltbar in
   *Einstellungen → Allgemein*, Standard **aus**.
3. „Dead clicks“ grob: Klicks auf Elemente mit `cursor:pointer` ohne Handler zählen
   (nur Zähler, kein Inhalt).

Mit zwei bis vier Wochen Daten wird diese Tabelle neu gerankt; bis dahin gilt die Annahme oben.
Der Punkt „Data-driven“ der CALM-Checkliste ist damit **vorläufig nur teilweise erfüllt**.
