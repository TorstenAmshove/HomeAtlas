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
- **Constitution nachziehen.** Die Regeln aus den ADRs stehen als Einzeiler mit Link in
  [`docs/specs/constitution.md`](../specs/constitution.md); die Begründung steht nur hier. Ein neues
  oder ersetzendes ADR bringt im selben PR die passende Regel dort mit (neu, geändert oder auf das
  neue ADR umverlinkt). `python docs/specs/trace_specs.py --check` scheitert sonst.

## Index

| Nr. | Titel | Status |
|---|---|---|
| [0001](0001-adrs-festhalten.md) | Architekturentscheidungen als ADRs festhalten | Akzeptiert |
| [0002](0002-lese-schreib-trennung.md) | Harte Trennung von lesenden und schreibenden Modulen | Ersetzt durch ADR-0011 |
| [0003](0003-host-netzwerk-und-loopback-backend.md) | Host-Netzwerk, Backend nur auf Loopback | Akzeptiert |
| [0004](0004-llm-faehigkeitsgrenze.md) | `tools.py` als vollständige Fähigkeitsgrenze des LLM | Ersetzt durch ADR-0013 |
| [0005](0005-sqlite-ohne-orm.md) | SQLite über ein flaches `db.py`, ohne ORM | Ersetzt durch ADR-0010 |
| [0006](0006-providerneutraler-llm-client.md) | Providerneutraler LLM-Client ohne Vendor-SDK | Ersetzt durch ADR-0020 |
| [0007](0007-credentials-fernet-schluessel-im-volume.md) | Credentials mit Fernet, Schlüssel im selben Volume | Akzeptiert |
| [0008](0008-topologie-als-server-svg.md) | Netzplan als serverseitiges SVG | Ersetzt durch ADR-0009 |
| [0009](0009-netzplan-ebenen-ist-stand.md) | Netzplan-Ebenen: wichtige Geräte im Bild, Rest als Liste | Akzeptiert |
| [0010](0010-db-als-paket.md) | `db` als Paket je Entität, SQL weiterhin nur dort | Akzeptiert |
| [0011](0011-lese-schreib-trennung-routen-module.md) | Lese-/Schreib-Trennung mit Routen-Modulen | Ersetzt durch ADR-0012 |
| [0012](0012-lesender-websocket-fuer-ha-traces.md) | Lesender WebSocket für Home-Assistant-Traces | Ersetzt durch ADR-0013 |
| [0013](0013-rollos-per-set-switch.md) | Rollos per `set_switch`, Tore bleiben gesperrt | Ersetzt durch ADR-0014 |
| [0014](0014-erreichbarkeits-quellen-lesend.md) | Lesende Erreichbarkeits-Quellen (Forced-Command, Cloudflare, öffentliches DNS) | Ersetzt durch ADR-0015 |
| [0015](0015-lesender-zugriff-klassische-unifi-api.md) | Lesender Live-Zugriff auf die klassische UniFi-API | Ersetzt durch ADR-0016 |
| [0016](0016-unifi-scan-nur-mit-api-key.md) | Scan der klassischen UniFi-API nur mit API-Key | Ersetzt durch ADR-0017 |
| [0017](0017-firewall-quellen-und-pfadbewertung.md) | Firewall-Quellen lesen und Pfade von HomeAtlas bewerten | Ersetzt durch ADR-0018 |
| [0018](0018-wan-status-und-lesepfade.md) | WAN-Status lesen, HA-Systemprotokoll, Dachfenster gesperrt | Ersetzt durch ADR-0019 |
| [0019](0019-firewall-zonen-subnetze.md) | Firewall-Zonen über die Subnetze aus `networkconf` zuordnen | Ersetzt durch ADR-0021 |
| [0020](0020-llm-client-ohne-schwesterprojekt.md) | Providerneutraler LLM-Client ohne Vendor-SDK, ohne Schwesterprojekt | Akzeptiert |
| [0021](0021-proxmox-live-lesepfade.md) | Lesender Live-Zugriff auf die Proxmox-API für den Assistenten | Ersetzt durch ADR-0022 |
| [0022](0022-container-live-status.md) | Live-Status lokaler Docker-Container für den Assistenten, ohne Inspect | Ersetzt durch ADR-0023 |
| [0023](0023-keine-fernwartung.md) | Keine Fernwartung, einzige Steuerung ist Home-Assistant-Schalten | Ersetzt durch ADR-0025 |
| [0024](0024-docker-socket-proxy.md) | Docker nur lesend über einen mitgelieferten Socket-Proxy, kein Inspect | Akzeptiert |
| [0025](0025-unifi-scan-client-port-und-port-vlans.md) | UniFi-Scan liest Client-Zuordnung und Port-VLANs aus der klassischen API | Akzeptiert |
