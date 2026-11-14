# ADR-0006: Providerneutraler LLM-Client ohne Vendor-SDK

- **Status:** Akzeptiert (nachträglich dokumentiert)
- **Datum:** 2026-11-14

## Kontext
Der Haushalt wählt den LLM-Anbieter selbst (Claude, OpenAI, Gemini, DeepSeek, lokales Ollama).
Das Schwesterprojekt GlucoSphere-Web hat ein gleich aufgebautes `llm_providers.py`.

## Entscheidung
- `llm_providers.py` spricht rohes HTTP über `httpx`, kein Vendor-SDK.
- Struktur bleibt erkennbar gleich zu GlucoSphere-Webs `llm_providers.py`.
- An Anthropic werden **nie** Sampling-Parameter (`temperature`, `top_p`, `top_k`) gesendet und
  `thinking` wird **nie** explizit konfiguriert – beides führt auf aktuellen Claude-Modellen zu
  HTTP 400 (Details im Modul-Docstring).

## Konsequenzen
- Ein neuer Anbieter ist eine neue Funktion in `llm_providers.py`, keine neue Abhängigkeit.
- „Temperatur für Claude wieder einführen“ oder „SDK verwenden“ ist ein Verstoß.
