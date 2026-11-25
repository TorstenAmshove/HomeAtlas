# ADR-0026: Port-VLANs im UniFi-Scan über Netz-IDs aus `networkconf` auflösen

- **Status:** Akzeptiert, ergänzt ADR-0025
- **Datum:** 2026-11-25

## Kontext
ADR-0025 erlaubt `stat/device` und `rest/portconf` für die VLAN-Zuordnung je Switchport. Die Port-Felder
(`native_networkconf_id`, `excluded_networkconf_ids`, `portconf_id`) tragen die `_id` aus `rest/networkconf`. Die
Netz-Ressourcen der Integration-API (`networkResources`) tragen dagegen die UUID der Integration-API; beide IDs
sind nicht gleich. Ohne die `_id` und die VLAN-ID aus `rest/networkconf` lässt sich eine Netz-ID nicht zu VLAN-ID
und Name auflösen.

## Entscheidung
ADR-0025 gilt unverändert weiter. Zusätzlich:
- **`rest/networkconf` (bestehender Pfad, nur GET):** zu `name`, `purpose`, `wan_*` (ADR-0018) dürfen zusätzlich
  `_id` und `vlan` gelesen werden. Zugangsdaten und alle `x_*`-Felder (Passphrasen, PPPoE) bleiben verworfen.
- **Auflösung im Probe:** Netz-IDs werden je Site zu VLAN-ID und Name aufgelöst. Gespeichert werden nur die
  aufgelösten Werte (`extra.unifi.ports`), keine IDs und keine MACs. Eine ID ohne Treffer in derselben Site
  erscheint als „unbekanntes Netz“.
- **Tagged-Modus:** `auto` wird „alle“ (mit `excluded_networkconf_ids`: „alle außer …“), `block_all` „keine“,
  `custom` und Unbekanntes „benutzerdefiniert“. Die konkrete Tagged-Liste von `custom` steht nicht in der
  Positivliste und wird nicht gelesen.
- **Verwendung:** Anzeige im Gerätedetail und in der Doku. Die Daten gelangen nicht in LLM-Kontext
  (`tools.py` bleibt unberührt).
- **Obergrenzen:** wie ADR-0025 (128 Ports je Gerät, 200 Profile je Site).

## Konsequenzen
- Port-VLANs sind lesbar, ohne Schreibzugriff, ohne neuen Pfad außer `rest/portconf` aus ADR-0025.
- Reviewer erkennen Verstöße an `_id`-Werten oder `x_*`-Feldern im gespeicherten Ergebnis und an Pfaden außerhalb
  der Liste aus ADR-0025.
