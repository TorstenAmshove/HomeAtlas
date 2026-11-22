# ADR-0017: Firewall-Quellen lesen und Pfade von HomeAtlas bewerten

- **Status:** Akzeptiert, ersetzt ADR-0016
- **Datum:** 2026-11-22

## Kontext
Issue #106: Der Assistent soll beantworten, ob eine Firewall einen Weg sperrt. Die Regeln liegen auf
dem UniFi-Gateway und auf Hosts (nftables). Beides braucht Außenkontakte, die ADR-0016 nicht kennt:
weitere UniFi-GETs (Policies, Zonen, Adress-/Port-Gruppen) und einen SSH-Befehl, der `sudo` braucht
(`nft -j list ruleset` zeigt den live geladenen Regelsatz, das geht nur mit Rechten). Spike des Owners
(UniFi Network 11.0.103, nur GET mit `X-API-Key`): `v2/api/site/<site>/firewall-policies` und
`…/firewall/zone` liefern 200, `api/s/<site>/rest/firewallgroup` liefert 200, die v2-Gruppenpfade 404.

## Entscheidung
Alles aus ADR-0016 gilt unverändert weiter (und damit ADR-0015/0014/0013: Forced-Command mit fester
Befehlskonstante, Parser mit Positivliste, Außenkontakte nur lesend und opt-in, jeder weitere
SSH-Befehl, jedes weitere Außenziel oder jeder weitere nicht-GET-Aufruf braucht ein neues ADR;
`tools.py` als vollständige Fähigkeitsgrenze, `set_switch`-Ausnahme, WebSocket nur
`trace/list`/`trace/get`; `unifi_live.py` mit genau einem lesenden Event-POST). Neu:
- **UniFi-Firewall lesen** (`firewall_unifi.py`): nur GET mit `X-API-Key`, keine Weiterleitungen, drei
  feste Pfade je Site: `v2/api/site/<site>/firewall-policies`, `v2/api/site/<site>/firewall/zone`,
  `api/s/<site>/rest/firewallgroup`. Zugang: Kategorie `unifi` mit `allowProbe`, Schalter
  `scanEnableFirewallUnifi` (Default aus). Keine Rohantworten, nur Positivliste der Felder.
- **nftables der Hosts lesen** (`firewall_nft.py`, folgt in einem eigenen PR): genau ein fester Befehl
  `nft -j list ruleset` per SSH-Forced-Command, auf dem Ziel per `authorized_keys`
  (`restrict,from=…,command="sudo /usr/sbin/nft -j list ruleset"`) und einen sudoers-Eintrag nur für
  genau diesen Befehl erzwungen. Das ist der **erste Privilegienwechsel** (`sudo`) im Lesepfad: er ist
  nötig, weil nur der live Regelsatz zeigt, was gilt, und bleibt auf diesen einen Befehl beschränkt.
  Das Modul ist eigenständig und berührt `probe_auth._SSH_COMMANDS` nicht. Zugang: Kategorie
  `firewall_nftables` mit `allowProbe`, Schalter `scanEnableFirewallNft` (Default aus).
- **Pfadbewertung** (`firewall_eval.py`, folgt): ein **reines** Modul (kein Netz, keine DB, kein SSH),
  das `tools.py` importieren darf. HomeAtlas bewertet („erlaubt / blockiert / unklar“), das LLM
  erklärt nur das Ergebnis und interpretiert keine Regeln. Das verletzt die Fähigkeitsgrenze nicht,
  weil das Modul nichts liest oder ändert; Lesemodule importiert `tools.py` weiterhin nicht.
- **Unklar statt Raten:** nicht auswertbare Regeln oder fehlende/veraltete Quellen ergeben „unklar“,
  nie „erlaubt“.
- Die Proxmox-Firewall ist in v1 ausgenommen (Owner nutzt sie nicht); ein späterer Zugriff braucht
  ein weiteres ADR.

## Konsequenzen
- Ein Zugang „UniFi Network (API-Key)“ mit „Zum Auslesen verwenden“ genügt für die UniFi-Firewall;
  der Key hat die Rechte seines Erstellers (siehe ADR-0016).
- Reviewer erkennen Verstöße an einem `post/put/delete/patch/request` in `firewall_unifi.py`, an einem
  Import aus `unifi_live`, an einem zweiten `connection.run(` in `firewall_nft.py` oder an einem Import
  eines Quell-/Schreibmoduls in `tools.py`/`firewall_eval.py`.
- ADR-0016 hat den Status „Ersetzt durch ADR-0017“.
