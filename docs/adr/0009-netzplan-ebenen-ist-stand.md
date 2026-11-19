# ADR-0009: Netzplan-Ebenen: wichtige Geräte im Bild, Rest als Liste

- **Status:** Akzeptiert, ersetzt ADR-0008
- **Datum:** 2026-11-19

## Kontext
ADR-0008 beschreibt den Netzplan mit den Ebenen Internet → Router → Verteilung → Server →
Endgeräte und Containern innerhalb ihres Hosts. Der Code (`topology.py`) zeichnet seit längerem
etwas anderes: Internet → Router → Verteilung → **Wichtige Geräte** (Bedeutung `critical`). Server,
Endgeräte und Container stehen gruppiert als Liste unter dem Bild; Container erscheinen nur als
Zähler bei kritischen Hosts. Die Rückgewinnung der Specs (`docs/specs/capabilities/topologie/spec.md`)
hat den Widerspruch sichtbar gemacht. Agenten, die ADR-0008 glauben, planen gegen ein Bild, das es
nicht gibt.

## Entscheidung
- Der Netzplan bleibt ein serverseitig erzeugtes SVG ohne Graph-Bibliothek im Browser und ohne
  Zoomen/Ziehen (unverändert aus ADR-0008).
- Ebenen von oben nach unten: Internet → Router → Verteilung (Switches, Access Points) →
  Wichtige Geräte. Leere Ebenen entfallen. Alle übrigen Geräte stehen gruppiert und gezählt als
  Liste unter dem Bild.
- Farbe ist nie das einzige Signal (unverändert aus ADR-0008). Dass der Status im Kasten heute nur
  über die Farbe erkennbar ist, ist ein Fehler im Code, keine Entscheidung.

## Konsequenzen
- `CLAUDE.md`, Glossar und Constitution beschreiben diese Ebenen.
- Wer Server oder Endgeräte wieder als eigene Ebene im Bild will, braucht ein neues ADR.
- ADR-0008 hat den Status „Ersetzt durch ADR-0009“.
