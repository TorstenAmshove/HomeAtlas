# Glossar

| Begriff | Bedeutung |
|---|---|
| **System** | Ein Eintrag im Inventar: physisches Gerät, VM, Container oder Dienst. In der Oberfläche „Gerät“. Entität `systems`. |
| **Art (kind)** | Kategorie eines Systems: router, network, server, nas, container, vm, pc, mobile, printer, camera, smarthome, climate, heating, energy, media, iot, other. |
| **Bedeutung (importance)** | critical / normal / low („kritisch“, „normal“, „gering“). Steuert Sortierung, Netzplan und Doku. |
| **Wichtiges Gerät / überwacht** | System mit eingeschalteter Dauerüberwachung (`monitored`); wird alle paar Sekunden per Port oder Ping geprüft. |
| **Bestätigt (confirmed)** | Ein Mensch hat das System bearbeitet; danach überschreibt keine Automatik die von Menschen gepflegten Felder. |
| **Erkennungsschlüssel (discoveryKey)** | Stabile Identität für die Wiedererkennung über Scans: `mac:…`, `ip:…` oder `docker:…`. |
| **Alias** | Frühere Identität eines Systems (z. B. alte MAC) nach dem Zusammenführen. |
| **Duplikat / Zusammenführen (Merge)** | Zwei Einträge für dasselbe Gerät; beim Zusammenführen bleiben die Gerätedetails erhalten, der zweite Eintrag wird zum Alias. |
| **Namenspräzedenz** | Feste Reihenfolge, welcher Name gewinnt: manuell > UniFi > Eigenangabe (UPnP, dann mDNS) > DNS-Hostname > Seitentitel > Hersteller + IP-Oktett. |
| **Scan** | Ein vollständiger Lauf: Erkennung → Docker → Auslesen mit Zugangsdaten → Klassifikation → Doku neu erzeugen. Manuell oder per Zeitplan. |
| **Erkennung (Discovery)** | Finden von Geräten ohne Zugangsdaten über Ping/ARP, Portscan, Reverse-DNS, mDNS, SSDP/UPnP, HTTP-Banner, Docker-API. |
| **Auslesen (Credentialed Probing)** | Streng lesendes Anmelden an einem Gerät mit einem freigegebenen Zugang, um Eckdaten zu lesen. |
| **Klassifikation** | LLM-gestützte Einordnung von Systemen, die die Regeln nicht sicher einordnen können. |
| **Zugang (Account)** | Gespeicherte Zugangsdaten (Passwort, SSH-Schlüssel, Token, WLAN, Vertrag …), verschlüsselt. Entität `accounts`. |
| **Zum Auslesen freigegeben (allowProbe)** | Opt-in je Zugang, ohne das wird ein Zugang nie automatisch benutzt. |
| **Zuordnung (Assignment)** | Ein Zugang gilt zusätzlich für ein weiteres System, eine ganze Geräteart oder ein Subnetz. |
| **Secret** | Der geschützte Teil eines Zugangs (Passwort, Schlüssel, Passphrase, Token). Verlässt den Server nur einzeln und nur für ADMIN. |
| **Netzwerkressource** | Netz/VLAN, WLAN oder WAN-Anschluss, gelesen aus einem Controller (UniFi, Omada). Entität `networkResources`. |
| **Controller** | Zentrale Verwaltung von Netzgeräten (UniFi Network, TP-Link Omada), über deren API HomeAtlas Geräte, Uplinks, VLANs, WLANs, WANs liest. |
| **Doku-Kapitel (Doc-Seite)** | Eines der 12 thematischen Markdown-Kapitel, aus dem Inventar erzeugt. Slug als Schlüssel. |
| **Manuelle Notizen** | Eigener Abschnitt je Kapitel, den die Generierung nie anfasst. |
| **Manueller Override** | Ganze Kapitelseite von Hand überschrieben; sie wird dann nicht mehr automatisch erzeugt, bis sie zurückgesetzt wird. |
| **Version** | Früherer Stand eines Kapitels (oder einer Gerätekonfiguration), abrufbar und wiederherstellbar. |
| **Netzplan (Topologie)** | Automatisch erzeugtes Bild des Netzes in festen Schichten: Internet → Router → Verteilung → Server → Endgeräte. Zusätzlich eine Layer-3-Ansicht (Netze/VLANs). |
| **Assistent** | Chat mit einem LLM, das über Werkzeuge das Inventar kennt und live nachmisst. |
| **Werkzeug (Tool)** | Eine Fähigkeit des Assistenten; die Liste ist die vollständige Fähigkeitsgrenze des Modells. |
| **MCP-Endpunkt** | Externer Zugang zu denselben Werkzeugen für andere KI-Clients (Model Context Protocol), abgesichert per Token. |
| **Diagnose** | Live-Messung: Ping, Port, DNS, HTTP, Traceroute, Internet-Check, Speedtest. |
| **Fernverwaltung (Remote-Admin)** | Schreibende Admin-Funktionen: Container steuern, Reboot, SSH-Konsole, Schlüssel ausrollen, Schalter. |
| **Einrichtungsassistent (Setup)** | Einmalige Ersteinrichtung nach der ersten Anmeldung und MFA. |
| **ADMIN / MEMBER** | Die zwei Rollen: Administrator / Mitglied (nur lesen, Assistent). |
| **[Muss] / [Impl]** | Markierung in diesen Specs: verbindlich auch für eine Alternative / nur Eigenart der heutigen Umsetzung. |
| **OFFEN** | In den Specs markierte Unklarheit oder Entscheidung, die vor dem Bau der Alternative zu klären ist. |
