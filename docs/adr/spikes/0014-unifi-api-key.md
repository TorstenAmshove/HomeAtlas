# Spike zu ADR-0014: Akzeptiert die klassische UniFi-API den API-Key?

Nur lesende GET-Aufrufe, keine Änderung am Controller. Auf einem Rechner im Heimnetz ausführen.
`UNIFI_URL` ist die Adresse des Controllers (z. B. `https://192.168.1.1`), `KEY` der bestehende
API-Key aus HomeAtlas. Den Key nicht in Issues, Kommentare oder Screenshots schreiben.

```bash
export UNIFI_URL=https://<controller>
read -rs KEY; export KEY            # Key eingeben, wird nicht angezeigt
B=$UNIFI_URL/proxy/network/api/s/default
for p in stat/sta stat/device stat/event stat/alarm stat/health rest/firewallrule; do
  printf '%-22s ' "$p"; curl -sk -o /dev/null -w '%{http_code}\n' -H "X-API-Key: $KEY" "$B/$p"
done
```

- **200** für einen Endpunkt: der Key reicht dort.
- **401/403**: der Key reicht nicht (dann Plan Teil B neu abstimmen, siehe ADR-0014).

Feldnamen ohne Werte ausgeben (für die Tabelle im ADR):

```bash
curl -sk -H "X-API-Key: $KEY" "$B/stat/sta" | jq '.data[0] | keys'
curl -sk -H "X-API-Key: $KEY" "$B/stat/device" | jq '.data[0] | keys'
curl -sk -H "X-API-Key: $KEY" "$B/stat/event?_limit=1" | jq '.data[0] | keys'
```

Trage in `0014-lesender-zugriff-klassische-unifi-api.md` HTTP-Status, UniFi-Version und die
relevanten Feldnamen (ohne Werte, MACs, Schlüssel) ein.
