# Architecture Decision Records (ADRs)

Kurze Dokumente, die **warum** eine Architekturentscheidung so gefallen ist festhalten – für
Menschen und für KI-Agenten, die sonst bewusste Entscheidungen „wegrefaktorieren“.

## Regeln

- **Nie still ändern.** Ändert sich eine Entscheidung, entsteht ein neues ADR mit
  `Status: Akzeptiert, ersetzt ADR-NNNN`; im alten wird nur der Status auf
  `Ersetzt durch ADR-MMMM` gesetzt.
- Wer (Mensch oder Agent) einer Entscheidung widersprechen will, schlägt ein neues ADR vor, statt
  sie im Code zu umgehen.
- Format: siehe `template.md`. Kurz halten – eine Bildschirmseite.

## Index

| Nr. | Titel | Status |
|---|---|---|
| [0001](0001-adrs-festhalten.md) | Architekturentscheidungen als ADRs festhalten | Akzeptiert |
| [0002](0002-lese-schreib-trennung.md) | Harte Trennung von lesenden und schreibenden Modulen | Akzeptiert |
| [0003](0003-host-netzwerk-und-loopback-backend.md) | Host-Netzwerk, Backend nur auf Loopback | Akzeptiert |
| [0004](0004-llm-faehigkeitsgrenze.md) | `tools.py` als vollständige Fähigkeitsgrenze des LLM | Akzeptiert |
| [0005](0005-sqlite-ohne-orm.md) | SQLite über ein flaches `db.py`, ohne ORM | Akzeptiert |
| [0006](0006-providerneutraler-llm-client.md) | Providerneutraler LLM-Client ohne Vendor-SDK | Akzeptiert |
| [0007](0007-credentials-fernet-schluessel-im-volume.md) | Credentials mit Fernet, Schlüssel im selben Volume | Akzeptiert |
| [0008](0008-topologie-als-server-svg.md) | Netzplan als serverseitiges SVG | Akzeptiert |
