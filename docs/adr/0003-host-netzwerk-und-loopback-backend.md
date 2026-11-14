# ADR-0003: Host-Netzwerk, Backend nur auf Loopback

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
Die Geräteerkennung liest die ARP-Tabelle des Hosts und sendet mDNS/SSDP-Multicast. Beides
überquert kein Docker-Bridge-Netz.

## Entscheidung
- Beide Container laufen mit `network_mode: host`.
- Das Backend bindet ausschließlich an `127.0.0.1` (Port `HOMEATLAS_API_PORT`, Standard 8281).
  Nur das nginx im Frontend-Container (Port 8280) erreicht es und leitet `/api/*` weiter.
- Ein Reverse Proxy (z. B. Traefik) bekommt nur eine Route zum Frontend, nie zum Backend.

## Konsequenzen
- Kein Docker-Bridge-Netz, keine Port-Mappings – Port-Kollisionen auf dem Host sind möglich und
  deshalb über Variablen einstellbar.
- Ein Bind auf `0.0.0.0` würde die API auf jeder Schnittstelle des Hosts veröffentlichen – Verstoß.
- Windows-/Docker-Desktop-Hosts sehen das LAN nur eingeschränkt.
