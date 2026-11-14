# ADR-0008: Netzplan als serverseitiges SVG

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
Der Netzplan richtet sich an Menschen, die keine Netzwerkdiagramme lesen.

## Entscheidung
`topology.py` rendert den Plan serverseitig als SVG mit fester Schichtenanordnung
(Internet → Router → Verteilung → Server → Endgeräte). Keine Graph-Bibliothek im Browser.
Nur wichtige Geräte als eigene Kästen, der Rest gruppiert und gezählt; Container innerhalb ihres
Hosts; Farbe nie als einziges Signal.

## Konsequenzen
- Kein zusätzliches JavaScript-Bundle für Diagramme.
- Interaktive Features (Zoomen, Ziehen) sind bewusst nicht vorgesehen; wer sie will, braucht ein
  neues ADR.
