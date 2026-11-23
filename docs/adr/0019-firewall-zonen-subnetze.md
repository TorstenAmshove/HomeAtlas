# ADR-0019: Firewall-Zonen über die Subnetze aus `networkconf` zuordnen

- **Status:** Ersetzt durch ADR-0021; ersetzte ADR-0018
- **Datum:** 2026-11-22

## Kontext
Der Abnahmetest von #106 gegen die echte Instanz (UniFi Network 11.0.103) zeigte: `firewall/zone` nennt
Netze mit der Controller-ID, das Inventar speichert die andere ID der Integration-API. Keine ID passte, jede
Pfadbewertung endete in „Zone nicht zuordenbar“. `api/s/<site>/rest/networkconf` führt die Controller-ID (`_id`)
zusammen mit `ip_subnet`. Der Pfad enthält auch WAN-Zugangsdaten und wird bereits von `unifi_classic_probe.py`
mit demselben Key gelesen, ist für `firewall_unifi.py` aber ein weiterer Lesepfad und braucht deshalb dieses ADR.

## Entscheidung
Alles aus ADR-0018 gilt unverändert weiter (und damit ADR-0017/0016/0015/0014/0013). Geändert:
- `firewall_unifi.py` liest je Site zusätzlich per GET `api/s/<site>/rest/networkconf`, also vier feste Pfade.
  Übernommen werden nur `_id` und `ip_subnet`, und nur als IPv4-Subnetz an der Zone (`cidrs`). Kein anderes Feld
  dieses Pfads wird gespeichert, zurückgegeben oder geloggt.
- `firewall_eval.py` bestimmt die Zone einer Adresse über diese Subnetze (längstes Präfix). Bleibt das
  mehrdeutig, ist das Ergebnis weiter „unklar“.

## Konsequenzen
- Die Pfadbewertung funktioniert ohne Abgleich mit den IDs der Integration-API.
- Fällt `networkconf` aus, gilt die UniFi-Firewall-Quelle als nicht lesbar (`stale`), wie bei den anderen Pfaden.
- Reviewer erkennen Verstöße an jedem weiteren aus `networkconf` übernommenen Feld in `firewall_unifi.py`.
- ADR-0018 hat den Status „Ersetzt durch ADR-0019“.
