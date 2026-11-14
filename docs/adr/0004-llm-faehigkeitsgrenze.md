# ADR-0004: `tools.py` als vollständige Fähigkeitsgrenze des LLM

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
Der Assistent (In-App-Chat und externer MCP-Endpunkt in `mcp_server.py`) beantwortet Fragen zum
Heimnetz für alle Rollen, auch MEMBER. Was ein Modell sieht, landet in Provider-Logs, Chatverläufen
und künftigen Kontextfenstern.

## Entscheidung
- `tools.py` definiert **alles**, was ein Modell tun kann. Es ist lesend plus begrenzte
  Live-Diagnosen (`diagnostics.py`: Argumentlisten statt Shell, Timeouts, validierte Hostnamen).
- Einzige schreibende Fähigkeit: `set_switch` (siehe ADR-0002).
- Gespeicherte Secrets erreichen nie ein Modell: `list_accounts` entfernt Passwörter; Tokens werden
  serverseitig entschlüsselt und benutzt, nie zurückgegeben.

## Konsequenzen
- Neue Assistenten-Fähigkeiten werden an dieser Grenze geprüft: Liest sie nur? Kann sie ein Secret
  offenlegen? Ist sie zeitlich und im Umfang begrenzt?
- Eine Fähigkeit, die etwas verändert, braucht ein neues ADR.
