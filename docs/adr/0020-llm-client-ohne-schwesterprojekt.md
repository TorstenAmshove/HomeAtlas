# ADR-0020: Providerneutraler LLM-Client ohne Vendor-SDK, ohne Schwesterprojekt

- **Status:** Akzeptiert
- **Datum:** 2026-11-23

## Kontext
Der Haushalt wählt den LLM-Anbieter selbst (Claude, OpenAI, Gemini, DeepSeek, lokales Ollama).
ADR-0006 verlangte zusätzlich, dass `llm_providers.py` einem Schwesterprojekt strukturell ähnlich
bleibt. Dieses Projekt existiert nicht mehr; die Bedingung ist gegenstandslos.

## Entscheidung
- `llm_providers.py` spricht rohes HTTP über `httpx`, kein Vendor-SDK.
- Es gibt keine Strukturparität mit einem anderen Projekt mehr.
- An Anthropic werden **nie** Sampling-Parameter (`temperature`, `top_p`, `top_k`) gesendet und
  `thinking` wird **nie** explizit konfiguriert – beides führt auf aktuellen Claude-Modellen zu
  HTTP 400 (Details im Modul-Docstring).

## Konsequenzen
- Ein neuer Anbieter ist eine neue Funktion in `llm_providers.py`, keine neue Abhängigkeit.
- „Temperatur für Claude wieder einführen“ oder „SDK verwenden“ ist ein Verstoß.
- Ersetzt ADR-0006; dessen Inhalt bleibt als Historie.
