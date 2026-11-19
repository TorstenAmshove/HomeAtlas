# Abdeckungsmatrix

> Erzeugt von `python docs/specs/trace_specs.py`, nicht von Hand bearbeiten.
> Quelle der linken Spalte ist der Code; rechts die Capability-Specs, die den Eintrag nennen.

Lücken: **0**

## Routen (85)

| Eintrag | Spec |
|---|---|
| `GET /api/access-log` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `GET /api/accounts` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `POST /api/accounts` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `DELETE /api/accounts/{account_id}` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `PATCH /api/accounts/{account_id}` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `GET /api/accounts/{account_id}/assignments` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `PUT /api/accounts/{account_id}/assignments` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `POST /api/accounts/{account_id}/deploy` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `GET /api/accounts/{account_id}/secret` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `POST /api/auth/login` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `POST /api/auth/logout` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `GET /api/auth/me` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `POST /api/auth/mfa/confirm` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `POST /api/auth/mfa/setup` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `POST /api/auth/password` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `GET /api/auth/password-policy` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `GET /api/chats` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `POST /api/chats` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `DELETE /api/chats/{chat_id}` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `GET /api/chats/{chat_id}/messages` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `POST /api/chats/{chat_id}/messages` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `GET /api/dashboard` | [dashboard](capabilities/dashboard/spec.md) |
| `POST /api/diagnostics` | [dashboard](capabilities/dashboard/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `POST /api/diagnostics/dns` | [diagnose](capabilities/diagnose/spec.md) |
| `POST /api/diagnostics/speedtest` | [diagnose](capabilities/diagnose/spec.md) |
| `GET /api/docs` | [dokumentation](capabilities/dokumentation/spec.md) |
| `POST /api/docs/generate` | [dokumentation](capabilities/dokumentation/spec.md) |
| `GET /api/docs/{slug}` | [dokumentation](capabilities/dokumentation/spec.md) |
| `PUT /api/docs/{slug}` | [dokumentation](capabilities/dokumentation/spec.md) |
| `PUT /api/docs/{slug}/manual` | [dokumentation](capabilities/dokumentation/spec.md) |
| `POST /api/docs/{slug}/reset` | [dokumentation](capabilities/dokumentation/spec.md) |
| `GET /api/docs/{slug}/versions` | [dokumentation](capabilities/dokumentation/spec.md) |
| `GET /api/docs/{slug}/versions/{version_id}` | [dokumentation](capabilities/dokumentation/spec.md) |
| `POST /api/docs/{slug}/versions/{version_id}/restore` | [dokumentation](capabilities/dokumentation/spec.md) |
| `GET /api/health` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md) |
| `MOUNT /api/mcp` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `GET /api/monitor` | [monitoring](capabilities/monitoring/spec.md) |
| `POST /api/monitor/run` | [monitoring](capabilities/monitoring/spec.md) |
| `GET /api/network-resources` | [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) |
| `PATCH /api/network-resources/{resource_id}` | [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) |
| `GET /api/scans` | [discovery-und-scan](capabilities/discovery-und-scan/spec.md) |
| `POST /api/scans` | [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [klassifikation-llm](capabilities/klassifikation-llm/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md), [topologie](capabilities/topologie/spec.md) |
| `GET /api/scans/{scan_id}` | [discovery-und-scan](capabilities/discovery-und-scan/spec.md) |
| `GET /api/settings` | [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md), [monitoring](capabilities/monitoring/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md) |
| `PATCH /api/settings` | [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md), [monitoring](capabilities/monitoring/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `POST /api/settings/llm/models` | [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md) |
| `POST /api/settings/llm/test` | [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md) |
| `GET /api/settings/mcp-tokens` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `POST /api/settings/mcp-tokens` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `DELETE /api/settings/mcp-tokens/{token_id}` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `POST /api/settings/oui/refresh` | [discovery-und-scan](capabilities/discovery-und-scan/spec.md) |
| `POST /api/setup` | [setup-wizard](capabilities/setup-wizard/spec.md) |
| `GET /api/systems` | [inventar](capabilities/inventar/spec.md), [topologie](capabilities/topologie/spec.md) |
| `POST /api/systems` | [inventar](capabilities/inventar/spec.md) |
| `GET /api/systems/duplicates` | [inventar](capabilities/inventar/spec.md) |
| `DELETE /api/systems/{system_id}` | [inventar](capabilities/inventar/spec.md) |
| `GET /api/systems/{system_id}` | [inventar](capabilities/inventar/spec.md) |
| `PATCH /api/systems/{system_id}` | [inventar](capabilities/inventar/spec.md) |
| `GET /api/systems/{system_id}/aliases` | [inventar](capabilities/inventar/spec.md) |
| `GET /api/systems/{system_id}/config-versions` | [inventar](capabilities/inventar/spec.md) |
| `GET /api/systems/{system_id}/config-versions/{version_id}` | [inventar](capabilities/inventar/spec.md) |
| `GET /api/systems/{system_id}/container/logs` | [remote-admin](capabilities/remote-admin/spec.md) |
| `POST /api/systems/{system_id}/container/{action}` | [remote-admin](capabilities/remote-admin/spec.md) |
| `GET /api/systems/{system_id}/errors` | [inventar](capabilities/inventar/spec.md) |
| `POST /api/systems/{system_id}/ha-switch/{action}` | [remote-admin](capabilities/remote-admin/spec.md) |
| `GET /api/systems/{system_id}/ha-switchables` | [remote-admin](capabilities/remote-admin/spec.md) |
| `POST /api/systems/{system_id}/merge` | [inventar](capabilities/inventar/spec.md) |
| `POST /api/systems/{system_id}/not-duplicate` | [inventar](capabilities/inventar/spec.md) |
| `POST /api/systems/{system_id}/probe` | [credentialed-probing](capabilities/credentialed-probing/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) |
| `POST /api/systems/{system_id}/reboot` | [remote-admin](capabilities/remote-admin/spec.md) |
| `GET /api/systems/{system_id}/remote-containers` | [remote-admin](capabilities/remote-admin/spec.md) |
| `GET /api/systems/{system_id}/remote-containers/{container_id}/logs` | [remote-admin](capabilities/remote-admin/spec.md) |
| `POST /api/systems/{system_id}/remote-containers/{container_id}/{action}` | [remote-admin](capabilities/remote-admin/spec.md) |
| `POST /api/systems/{system_id}/shelly-switch/{action}` | [remote-admin](capabilities/remote-admin/spec.md) |
| `POST /api/systems/{system_id}/ssh-keys` | [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `GET /api/topology-layer3.svg` | [topologie](capabilities/topologie/spec.md) |
| `GET /api/topology.svg` | [topologie](capabilities/topologie/spec.md) |
| `GET /api/users` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `POST /api/users` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `DELETE /api/users/{user_id}` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `PATCH /api/users/{user_id}` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `POST /api/users/{user_id}/mfa/reset` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `WS /api/ws/systems/{system_id}/docker-console` | [remote-admin](capabilities/remote-admin/spec.md) |
| `WS /api/ws/systems/{system_id}/remote-docker-console` | [remote-admin](capabilities/remote-admin/spec.md) |
| `WS /api/ws/systems/{system_id}/ssh-console` | [remote-admin](capabilities/remote-admin/spec.md) |

## Tabellen (19)

| Eintrag | Spec |
|---|---|
| `accessLog` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [auth-und-rollen](capabilities/auth-und-rollen/spec.md), [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [monitoring](capabilities/monitoring/spec.md), [remote-admin](capabilities/remote-admin/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `accountAssignments` | [credentialed-probing](capabilities/credentialed-probing/spec.md), [inventar](capabilities/inventar/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `accounts` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [credentialed-probing](capabilities/credentialed-probing/spec.md), [dashboard](capabilities/dashboard/spec.md), [dokumentation](capabilities/dokumentation/spec.md), [inventar](capabilities/inventar/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md), [remote-admin](capabilities/remote-admin/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `apiTokens` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `chatMessages` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `chats` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `deviceConfigVersions` | [credentialed-probing](capabilities/credentialed-probing/spec.md), [inventar](capabilities/inventar/spec.md) |
| `deviceErrorEvents` | [credentialed-probing](capabilities/credentialed-probing/spec.md), [inventar](capabilities/inventar/spec.md), [monitoring](capabilities/monitoring/spec.md) |
| `docPageVersions` | [dokumentation](capabilities/dokumentation/spec.md) |
| `docPages` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [dokumentation](capabilities/dokumentation/spec.md) |
| `duplicateDismissals` | [inventar](capabilities/inventar/spec.md) |
| `monitorEvents` | [inventar](capabilities/inventar/spec.md), [monitoring](capabilities/monitoring/spec.md) |
| `networkResources` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [credentialed-probing](capabilities/credentialed-probing/spec.md), [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [dokumentation](capabilities/dokumentation/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md), [topologie](capabilities/topologie/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `scans` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [dashboard](capabilities/dashboard/spec.md), [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [dokumentation](capabilities/dokumentation/spec.md), [klassifikation-llm](capabilities/klassifikation-llm/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md), [topologie](capabilities/topologie/spec.md) |
| `sessions` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `settings` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [auth-und-rollen](capabilities/auth-und-rollen/spec.md), [dashboard](capabilities/dashboard/spec.md), [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [dokumentation](capabilities/dokumentation/spec.md), [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md), [inventar](capabilities/inventar/spec.md), [klassifikation-llm](capabilities/klassifikation-llm/spec.md), [monitoring](capabilities/monitoring/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md), [topologie](capabilities/topologie/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `systemAliases` | [inventar](capabilities/inventar/spec.md) |
| `systems` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [credentialed-probing](capabilities/credentialed-probing/spec.md), [dashboard](capabilities/dashboard/spec.md), [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [dokumentation](capabilities/dokumentation/spec.md), [inventar](capabilities/inventar/spec.md), [klassifikation-llm](capabilities/klassifikation-llm/spec.md), [monitoring](capabilities/monitoring/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md), [remote-admin](capabilities/remote-admin/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md), [topologie](capabilities/topologie/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `users` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md), [setup-wizard](capabilities/setup-wizard/spec.md) |

## KI-Werkzeuge (16)

| Eintrag | Spec |
|---|---|
| `list_systems` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `get_system` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `network_overview` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `list_documentation` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [dokumentation](capabilities/dokumentation/spec.md) |
| `get_documentation` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [dokumentation](capabilities/dokumentation/spec.md) |
| `list_accounts` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `list_containers` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `list_switches` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [remote-admin](capabilities/remote-admin/spec.md) |
| `set_switch` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [auth-und-rollen](capabilities/auth-und-rollen/spec.md), [remote-admin](capabilities/remote-admin/spec.md) |
| `internet_check` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [dashboard](capabilities/dashboard/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `ping_host` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `check_port` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [diagnose](capabilities/diagnose/spec.md), [monitoring](capabilities/monitoring/spec.md) |
| `dns_lookup` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `reverse_dns` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `http_check` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `traceroute` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [diagnose](capabilities/diagnose/spec.md) |

## Seiten (15)

| Eintrag | Spec |
|---|---|
| `AccessLogPage` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `AccountsPage` | [remote-admin](capabilities/remote-admin/spec.md), [zugangsdaten](capabilities/zugangsdaten/spec.md) |
| `ChatPage` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md) |
| `DashboardPage` | [dashboard](capabilities/dashboard/spec.md), [diagnose](capabilities/diagnose/spec.md) |
| `DocsPage` | [dokumentation](capabilities/dokumentation/spec.md) |
| `InventoryPage` | [inventar](capabilities/inventar/spec.md) |
| `LoginPage` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `MfaEnrollPage` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |
| `NetworksPage` | [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) |
| `PlanPage` | [diagnose](capabilities/diagnose/spec.md), [monitoring](capabilities/monitoring/spec.md), [topologie](capabilities/topologie/spec.md) |
| `ScanPage` | [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [klassifikation-llm](capabilities/klassifikation-llm/spec.md) |
| `SettingsPage` | [assistent-chat-und-mcp](capabilities/assistent-chat-und-mcp/spec.md), [auth-und-rollen](capabilities/auth-und-rollen/spec.md), [diagnose](capabilities/diagnose/spec.md), [discovery-und-scan](capabilities/discovery-und-scan/spec.md), [einstellungen-und-llm-provider](capabilities/einstellungen-und-llm-provider/spec.md), [monitoring](capabilities/monitoring/spec.md), [netzwerkressourcen-vlans](capabilities/netzwerkressourcen-vlans/spec.md) |
| `SetupPage` | [setup-wizard](capabilities/setup-wizard/spec.md) |
| `SystemDetailPage` | [credentialed-probing](capabilities/credentialed-probing/spec.md), [inventar](capabilities/inventar/spec.md), [klassifikation-llm](capabilities/klassifikation-llm/spec.md), [monitoring](capabilities/monitoring/spec.md), [remote-admin](capabilities/remote-admin/spec.md) |
| `UsersPage` | [auth-und-rollen](capabilities/auth-und-rollen/spec.md) |

## ADRs in der Constitution (11)

Quelle links sind die Dateien in `docs/adr/`, rechts die Regeln in [constitution.md](constitution.md),
die auf das ADR verlinken.

| ADR | Status | Regeln | Problem |
|---|---|---|---|
| [ADR-0001](../adr/0001-adrs-festhalten.md) | Akzeptiert | – |  |
| [ADR-0002](../adr/0002-lese-schreib-trennung.md) | Ersetzt durch ADR-0011 (ursprünglich akzeptiert, nachträglich dokumentiert) | – |  |
| [ADR-0003](../adr/0003-host-netzwerk-und-loopback-backend.md) | Akzeptiert (nachträglich dokumentiert) | B1, B2, B3, B6 |  |
| [ADR-0004](../adr/0004-llm-faehigkeitsgrenze.md) | Akzeptiert (nachträglich dokumentiert) | L5, K1, K2, K3 |  |
| [ADR-0005](../adr/0005-sqlite-ohne-orm.md) | Ersetzt durch ADR-0010 | – |  |
| [ADR-0006](../adr/0006-providerneutraler-llm-client.md) | Akzeptiert (nachträglich dokumentiert) | K5, K6, K7 |  |
| [ADR-0007](../adr/0007-credentials-fernet-schluessel-im-volume.md) | Akzeptiert (nachträglich dokumentiert) | Z1, Z2, Z3, Z5 |  |
| [ADR-0008](../adr/0008-topologie-als-server-svg.md) | Ersetzt durch ADR-0009 (ursprünglich akzeptiert, nachträglich dokumentiert) | – |  |
| [ADR-0009](../adr/0009-netzplan-ebenen-ist-stand.md) | Akzeptiert, ersetzt ADR-0008 | D4, D5 |  |
| [ADR-0010](../adr/0010-db-als-paket.md) | Akzeptiert, ersetzt ADR-0005 | D1, D2 |  |
| [ADR-0011](../adr/0011-lese-schreib-trennung-routen-module.md) | Akzeptiert, ersetzt ADR-0002 | L1, L2, L4, L5, L6 |  |
