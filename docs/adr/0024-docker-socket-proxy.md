# ADR-0024: Docker nur lesend über einen mitgelieferten Socket-Proxy, kein Inspect

- **Status:** Akzeptiert, ergänzt ADR-0023
- **Datum:** 2026-11-24

## Kontext
Das Backend mountete den rohen Docker-Socket des Hosts. `:ro` schützt nur die Socket-Datei, nicht die Docker-API:
Wer das Backend übernimmt, kann Container starten und den Docker-Host übernehmen. HomeAtlas ruft seit ADR-0023
nur noch GET-Endpunkte auf. Ein Proxy, der nur nach Bereich freischaltet (z. B. `CONTAINERS=1`), ließe aber alle
GET-Pfade unter `/containers` durch, darunter Inspect (`Config.Env` im Klartext), Logs, Archive und Export. Ein
Proxy filtert nach Methode und Pfad, nicht nach Inhalt (Issue #101).

## Entscheidung
- **Das Backend mountet den Docker-Socket nicht mehr.** `docker-compose.yml` enthält einen Dienst `docker-proxy`
  (`wollomatic/socket-proxy`, Version plus Digest, von Renovate gepflegt). Nur er mountet `/var/run/docker.sock`.
- **Pfadgenaue Allowlist, nur GET:** `/version`, `/info`, `/containers/json`, `/networks`, `/volumes` (optional mit
  Versionspräfix `/v1.NN`). Alles andere ist gesperrt: Inspect, Logs, Archive, Export, Exec und jede schreibende
  Methode.
- **Kein TCP-Port.** Der Proxy hat `network_mode: none` und stellt einen Unix-Socket in einem gemeinsamen
  Compose-Volume bereit, das das Backend nur liest. Als Rückfall ist `DOCKER_HOST=tcp://127.0.0.1:<Port>` erlaubt;
  `tcp://` mit anderem Host lehnt `docker_probe.py` ab.
- **Endpunkt-Auflösung in `docker_probe.py`:** `DOCKER_HOST` (`unix://`, loopback-`tcp://`), dann `DOCKER_SOCKET`
  (Bestandsinstallationen mit direktem Mount), dann `/var/run/docker.sock`. Fehlt der Endpunkt, meldet die Doku
  „Docker-Zugriff nicht eingerichtet“, alles andere läuft weiter.
- **Kein Inspect, nirgends.** Env-Werte werden nie gelesen oder gespeichert. Die Hostnamen von DDNS-Containern
  (Erkennung am Image bleibt) kommen aus dem vom Betreiber gesetzten Label `homeatlas.ddns.hosts` (kommagetrennt;
  optional `homeatlas.ddns.ipv6=true|false`), das `/containers/json` ohnehin liefert. Das ändert die Aussage aus
  ADR-0022, `probe()` lese die DynDNS-Umgebung per Inspect: Das entfällt. ADR-0022 selbst bleibt unverändert.
- **Erkennung von Vollzugriff:** Ein Container mit Bind-Mount von `docker.sock` (auch `:ro`) wird aus den `Mounts`
  von `/containers/json` erkannt und in Doku, Containerseite und `list_containers` (Feld `dockerSocket`) mit
  Hinweis und Empfehlung Socket-Proxy gezeigt. Bekannte Proxy-Images werden nicht markiert.
- Die Fähigkeitsgrenze in `tools.py` wächst nicht: nur ein Feld mehr in `list_containers`, keine neuen Importe.

## Konsequenzen
- Eine Übernahme des Backends ergibt weder Root auf dem Docker-Host noch Zugriff auf Container-Geheimnisse über
  Docker. Der Proxy läuft als Root ohne Capabilities (das Image-Standardkonto darf den Socket nicht öffnen),
  schreibgeschützt und ohne Netz.
- Wer das Compose-File nicht nachzieht, behält den direkten Mount (über `DOCKER_SOCKET`) und damit den alten
  Schutzstand. Das Compose im Deploy-Repo `ansible-docker.lan` ist nicht Teil dieses Repositories.
- DDNS-Hostnamen erscheinen nur noch, wenn das Label am DDNS-Container gesetzt ist; ohne Label bleibt die Liste leer.
- Reviewer erkennen Verstöße an einem zweiten Dienst mit Socket-Mount, einer erweiterten Allowlist
  (`test_compose_proxy.py`) oder einem Aufruf von `/containers/{id}/…` in `docker_probe.py`.
