# HomeAtlas in Netzen mit mehreren VLANs

HomeAtlas hängt in einem Netz und erreicht weitere VLANs nur **geroutet über das Gateway**. Diese
Seite beschreibt, was dabei funktioniert, was nicht, und was am Gateway (UniFi UCG Ultra als
Beispiel) eingestellt werden kann. Bei jedem Scan zeigt HomeAtlas pro geroutetem Scan-Netz eine
Warnung mit Verweis hierher.

Kennzeichnung: **(nicht verifiziert)** = aus Dokumentation oder Erfahrungsberichten abgeleitet,
nicht an einer echten UCG Ultra geprüft.

## Funktionsmatrix

| Funktion | Eigenes VLAN (direkt angebunden) | Nur über Gateway |
|---|---|---|
| Ping | ja | ja |
| TCP-Portscan | ja | ja, sofern die Firewall zwischen den VLANs die Ports erlaubt |
| Reverse-DNS | ja | ja |
| HTTP-Banner / Seitentitel | ja | ja (Firewall beachten) |
| ARP / MAC | ja | **nein** – die ARP-Tabelle enthält höchstens die MAC des Gateways |
| Hersteller (OUI) | ja | **nein** – braucht die MAC |
| Stille Geräte (antworten auf nichts) | über ARP sichtbar | **nicht gefunden** |
| mDNS (Name, Modell) | ja | **nein**, außer das Gateway leitet mDNS weiter |
| SSDP/UPnP | ja | **nein** (nicht verifiziert: UniFi leitet SSDP nach bisherigem Kenntnisstand nicht weiter) |
| `discoveryKey` | `mac:<mac>` | nur IP; schwächere Wiedererkennung |
| UniFi-/Omada-Daten (Clients, Netze) | ja | **ja** – kommen vom Controller, unabhängig vom VLAN (Clients nur aus den gescannten Netzen) |

Weitere Grenzen: höchstens 1024 Adressen pro Netz; Firewall-Regeln zwischen den VLANs können Ports
blockieren, dann erscheint ein Gerät fälschlich als „nicht erreichbar".

## Was die UniFi-Anbindung für alle Netze liefert

Ist ein UniFi-Konto mit „Probe erlaubt" hinterlegt, liefert der Controller Clients **mit MAC**
aus den gescannten Netzen (Scan-Einstellungen; ohne Auswahl die Host-Interface-Netze; Clients ohne
IP entfallen) sowie die Netze selbst (`vlanId`, CIDR). Damit fehlt die MAC geroutet gefundener
Geräte großenteils nicht mehr.

**Zusammenführen:** Der Netzwerkscan sieht ein geroutetes Gerät nur per IP, der Controller kennt
es mit MAC. Ist die IP in HomeAtlas genau einem Eintrag zugeordnet und stammt einer der beiden
Funde vom Controller (UniFi/Omada), werden sie automatisch zusammengeführt, auch ohne gemeinsamen
Hostnamen. Bei mehreren Einträgen mit gleicher IP oder bei verschiedenen MACs passiert das nicht.
Bereits vorhandene Duplikate werden nicht rückwirkend bereinigt (dafür gibt es das manuelle
„Zusammenführen").

## Einstellungen am Gateway (UCG Ultra)

1. **mDNS weiterleiten:** Der Multicast-DNS-Proxy des UniFi-Gateways leitet mDNS zwischen Netzen
   weiter. Laut Ubiquiti ist er auf neuen Netzen standardmäßig aktiv und pro Netz abschaltbar
   (Einstellungen → Netzwerke → jeweiliges Netz). Prüfe, dass er in **allen** Netzen aktiv ist, in
   denen Namen erkannt werden sollen. Mehr Netze erzeugen mehr weitergeleiteten Verkehr.
   Ob alle Dienste (nicht nur Bonjour-Standardtypen) bei deiner Firmware ankommen: nicht verifiziert.
2. **SSDP:** Eine Weiterleitung ist nicht verifiziert. Prüfe im Firewall-Log, ob UDP 1900 /
   239.255.255.250 zwischen den VLANs blockiert wird. Ohne SSDP fehlen UPnP-Namen im fremden VLAN.
3. **Firewall: „HomeAtlas-Host darf zu allen Netzen, nicht umgekehrt".** Eine Regel vom
   HomeAtlas-Host (feste IP) in alle Scan-Netze, ohne Gegenrichtung. Nötig sind ausgehend ICMP
   (Ping), die gescannten TCP-Ports, ggf. SSH (22) für die SSH-Probe, die Docker-API-Ports (nur
   wenn Docker-Hosts in fremden VLANs gelesen werden) sowie HTTPS zum Controller.

## Option: Trunk / VLAN-Interfaces am Docker-Host

Der Host bekommt per Trunk-Port oder 802.1Q-Subinterfaces je VLAN ein Interface. Mit
`network_mode: host` scannt HomeAtlas diese Netze dann direkt (MAC, mDNS, SSDP), ohne
Codeänderung. **Das ist keine Standardempfehlung**, denn der Host (und jeder Container darauf)
hat dann Layer-2-Zugriff auf diese VLANs und umgeht die Gateway-Firewall. Wenn du es tust:

- Den Trunk nur die benötigten VLANs führen lassen (nicht „Allow All").
- Keine Standardroute auf den VLAN-Interfaces.
- Host-Firewall (`nftables`/`iptables`) verwirft eingehenden Verkehr aus diesen VLANs; HomeAtlas
  braucht nur ausgehenden.
- Weniger riskant ist ein reines Management-VLAN mit der Firewall-Regel oben.

Ein Scanner-Agent pro VLAN ist bewusst nicht vorgesehen (neuer Dienst, anderes Sicherheitsmodell).
Das Threat-Model steht im README-Abschnitt „Sicherheit".
