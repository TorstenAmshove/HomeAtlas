# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HomeAtlas is a self-hosted home-network documentation tool (German UI/docstrings mixed with
English code comments). It scans the home LAN, identifies devices via multiple independent
sources, generates plain-language Markdown documentation, and provides an LLM-backed
troubleshooting assistant. Two containers, both on `network_mode: host` (required — discovery
reads the host's ARP table and sends mDNS/SSDP multicast, neither of which crosses a Docker
bridge network):

```
Browser ── nginx (frontend, React/TS, :8280) ── /api/* ──▶ 127.0.0.1:8281 ──▶ FastAPI backend
```

The backend binds only to `127.0.0.1`; nginx is the only thing that can reach it, since the host
network means the API port is otherwise exposed on every interface of the Docker host.

Read the README.md "Sicherheit" section before touching auth, credential storage, or the
probe/remote-admin modules — it states the threat model and trade-offs this code is built around.

## Development commands

Backend (from `backend/`):
```bash
pip install -r requirements.txt
HOMEATLAS_DB_PATH=./dev.db HOMEATLAS_KEY_PATH=./dev.key ADMIN_PASSWORD=Dev-Passwort-2024 \
  uvicorn app.main:app --reload --port 8000
```

Frontend (from `frontend/`), proxies `/api` to `:8000` automatically:
```bash
npm install
npm run dev        # dev server
npm run build       # tsc -b && vite build — this IS the typecheck; there is no separate lint/typecheck script
npm run preview
```

Backend tests and lint (from `backend/`, CI runs both in `.github/workflows/test.yml`):
```bash
pip install -r requirements-dev.txt
ruff check .          # deliberately small rule set, see backend/ruff.toml; no formatter enforced
python -m pytest -q   # tests/ -- use the `temp_db` fixture for anything touching the `db/` package
```
The frontend has no linter or unit tests. Besides `npm run build`, CI runs a browser smoke test
(`frontend/e2e/`, its own Playwright package, excluded from the image via `frontend/.dockerignore`)
against the built images: job `smoke` in `build.yml` starts backend + frontend on the host network
with a throwaway DB and walks login → MFA enrollment → setup wizard → dashboard, a Markdown doc page
and a few routes; any console error or uncaught page error fails it. It needs a fresh backend each
run (it enrolls the admin). Locally, with a fresh backend on :8000 and `npm run build && npx vite
preview --port 8280` in `frontend/`:
```bash
cd frontend/e2e && npm ci
SMOKE_ADMIN_PASSWORD=Dev-Passwort-2024 SMOKE_CHROMIUM_PATH=/path/to/chrome npx playwright test
```
`SMOKE_CHROMIUM_PATH` is only for a pre-installed Chromium; otherwise run `npx playwright install chromium`.

Project hooks in `.claude/settings.json`: edited backend `.py` files are run through `ruff check
--fix` (remaining errors are fed back).

Full stack via Docker: `docker compose up -d --build`, then http://localhost:8280. First-run
admin credentials are printed once to `docker compose logs backend`. `ADMIN_USERNAME`/
`ADMIN_PASSWORD` in `docker-compose.yml` only take effect when no user exists yet, and a weak `ADMIN_PASSWORD` (policy violation) is replaced by a generated one.

Container releases are automated: a pull request against `master` builds both images without
pushing. Merging a code-changing pull request to `master` derives a shared Semver release from
Conventional Commits, creates `vX.Y.Z`, and publishes both GHCR images under `X.Y.Z`, `X.Y`, and
`latest`. `release.yml` also passes the computed version as build arg `HOMEATLAS_VERSION` (backend) and `VITE_APP_VERSION` (frontend); Settings → Über shows it, local and PR builds show `dev`. Documentation-only and `.github/**` pull requests do not release automatically.

Dependency updates come from the Mend Renovate App: `renovate.json` (repository root, not `.github/` - HomeAtlas is a fork, and Renovate only checks `forkProcessing` in the root `renovate.json`) on top of the shared presets in [TorstenAmshove/renovate-config](https://github.com/TorstenAmshove/renovate-config). Patch/digest updates and pip and npm minor updates are auto-merged by Renovate once Build (including the browser smoke test) and Test are green (so they release and deploy without a human); all majors are merged by hand. The base images use exact versions plus digest (`python:3.12.16-slim@sha256:…`, `node:26.13.1-alpine@…`, `nginx:1.30.6-alpine@…`), and the Python version of `backend/Dockerfile` and `test.yml` moves together in one "python runtime" PR.

Production deployment is not done from this repository: `ansible-docker.lan` rolls out the
published GHCR images on docker.lan (see README "Installation").

Windows containers lack `ip`/`ping`/`traceroute`, so discovery and diagnostics are degraded there;
this only matters when reasoning about cross-platform behavior, not for normal development.

## Backend architecture (`backend/app/`)

`main.py` only assembles the app (lifespan, MCP mount, router includes). HTTP routes live in
`routes/<group>.py`, one module per capability group matching `docs/specs/capabilities/`; the
session/role dependencies and helpers several groups share live in `deps.py`, which imports nothing
from `routes/`. A route module never imports another route module.

Every module has a docstring explaining its own design rationale and constraints — read the
module docstring before editing it, it usually answers "why is this written this way" before you
have to ask. Key structural rules that span multiple files:

**Read vs. write is a hard architectural split, not just a convention.** Modules that read from
devices/Docker and modules that change them are deliberately separate and never import each
other:
- `docker_probe.py` (read-only, GET-only Docker API calls) vs. `docker_admin.py` (write-capable
  container control) — the latter is reachable only from the admin-gated routes in `routes/remote.py`, never
  from `tools.py` or `pipeline.py`.
- `probe_auth.py` (read-only SSH/HTTP/TR-064 device probing, hardcoded command allowlist in
  `_SSH_COMMANDS` with no setting/parameter/tool able to extend it) vs. `remote_admin.py`
  (write-capable SSH admin: install keys, interactive shell, remote container control) — same
  "never imported by/into `tools.py`" rule. A future import from `tools.py` into either write
  module would be a bug, not a refactor.

**`tools.py` is the LLM's entire capability surface** (used by both the in-app chat and
`mcp_server.py`'s external MCP endpoint). It is read-only plus bounded live diagnostics, with one
documented exception (`set_switch`: Shelly relay / Home Assistant `switch`/`light` on/off plus shutter-class `cover`
open/close/stop, never garage doors, gates or windows, see ADR-0018; Home Assistant automation traces and the system-log fallback are read over a WebSocket limited to `trace/list`/`trace/get`/`system_log/list`, ADR-0018); live UniFi reads go through `unifi_live.py` (ADR-0017: fixed allowlist incl. exactly one read-only POST for the event log, `X-API-Key`, field allowlist) and live Proxmox reads through `proxmox_live.py` (ADR-0021: GET-only path allowlist, scan token, no task log text) and live local container status through `docker_probe.live_containers` (ADR-0022: exactly `GET /containers/json?all=1`, never inspect, field allowlist); these three are the only source modules `tools.py` may import; nothing else reachable from here mutates inventory, docs, or devices, and `list_accounts` always strips
passwords before they reach a model — secrets never enter a prompt, provider log, or chat
history. When adding a new assistant capability, this boundary is the thing to preserve.

**Discovery (`discovery.py`) is intentionally multi-source**: ping/ARP, port scan, reverse-DNS,
mDNS/SSDP, Docker API, each contributing because none alone sees everything. Naming precedence is
fixed: manually maintained HomeAtlas name > assigned UniFi name > self-reported name (UPnP
`friendlyName`, then mDNS) > DNS hostname > page title > vendor + IP octet. `classify.py`
(LLM-assisted identification) runs once per device, only over findings new to the inventory (`db.find_existing_for_discovery`; later scans never re-ask, the upsert keeps the result via `extra.aiConfidence`; admins re-run it per device via `POST /api/systems/{id}/classify`), and only over devices the rule-based guess in `discovery._guess`
couldn't confidently place, and a low-confidence LLM answer is discarded rather than stored. It never overwrites a name or kind
that a source supplied (manual, UniFi, Docker, Proxmox, Omada), nor a self-reported name (UPnP/mDNS/Shelly app name, `extra.nameSource`; `kind` may still be set) and skips Docker containers entirely
(they share the host IP, which is the key its answers are mapped by).

**`pipeline.py`** orchestrates a full scan (discovery → Docker → controller APIs (UniFi, Omada,
Proxmox, AdGuard) → classification → inventory merge → credentialed probing → doc regeneration; classification runs
before probing, so probe facts only inform the next scan's classification) and owns the scan `Scheduler`. **`docs.py`** renders the
14-chapter Markdown documentation from the inventory; each doc page has a separate
never-auto-touched "manual notes" field (`db.set_doc_page_manual`) plus an independent
whole-page-manual-override mode — know which one an edit is supposed to affect.

**`monitor.py`** is a background poller for devices flagged "important" — only status
*transitions* are persisted (not every poll), and a down state requires multiple consecutive
failures (`_FAILURES_BEFORE_DOWN`) before it's recorded, to avoid flagging normal Wi-Fi packet
loss as an outage.

**`db/`** (package, one module per entity group, ADR-0010) is the only place that touches SQLite — flat functions over a single
connection helper in `db/_core.py`, no ORM; `db/__init__.py` re-exports everything so callers write `db.get_system(...)`. `DB_PATH` and `_ERROR_EVENT_KEEP` live in `db/__init__.py` and are read at call time, so `monkeypatch.setattr(db, ...)` keeps working; submodules import only from `_core` (plus `accounts`→`systems`, `config_versions`→`settings`), never cyclically. **`crypto.py`** (Fernet, key stored alongside the DB in the same
volume — protects against a leaked DB copy, not a host-root attacker) encrypts credentials in
`accounts.secretEnc`; the API only ever returns a stored secret one-at-a-time from
`GET /api/accounts/{id}/secret`, admin-only, never in bulk.

**`llm_providers.py`** is a provider-neutral HTTP client (Claude/OpenAI/Gemini/DeepSeek/Ollama) —
deliberately not using any vendor SDK. Two correctness details specific to current Claude models:
no sampling parameters (`temperature`/`top_p`/`top_k`) are ever sent to Anthropic (removed on
Opus 5/Sonnet 5/4.8/4.7 — sending them is an HTTP 400), and `thinking` is never explicitly
configured (every explicit setting 400s on some model in the supported range).

**`auth.py`** implements two roles: ADMIN (full access including secrets) and MEMBER (docs +
chat, read-only, never a plaintext secret). `deps.py`'s `require_admin`/`current_user`
dependencies are the enforcement point — `current_user` also hard-requires TOTP enrollment
(`security.py`) on every route except the small allowlist needed to complete enrollment itself.

**`topology.py`** renders the network plan as server-side SVG (fixed layered layout: Internet →
Router → Verteilung → Wichtige Geräte, everything else listed below the picture; ADR-0009)
rather than a client-side graph library, so it stays a
picture a non-technical reader can actually parse.

## Frontend architecture (`frontend/src/`)

Plain React + react-router, no state library — `App.tsx` holds auth state (session user, MFA/setup
gating) in context and is the source of truth for the login → MFA-enroll → setup-wizard → app
gating sequence; the same order is enforced independently on the backend (see `current_user` in
`deps.py`), so a UI-only change here doesn't change what the API actually allows.

`lib/api.ts` is a single typed fetch wrapper — every backend call goes through `request()`, which
is where session-cookie handling, FastAPI validation-error flattening, and the "MFA re-enrolled
elsewhere, force reload" behavior all live. Add new endpoints here rather than calling `fetch`
directly from a page.

## Architecture decisions

`docs/adr/` records the cross-cutting decisions above (read/write split, host network, LLM
capability boundary, SQLite without ORM, provider-neutral LLM client, credential encryption, SVG
topology). Read the relevant ADR before changing one of those areas. Never edit an accepted ADR
to reverse it — propose a new ADR that supersedes it. ADRs hold the *why*; `docs/specs/constitution.md`
restates each ADR's rule as a one-liner with a link and no rationale. A new or superseding ADR updates
that rule in the same PR (`trace_specs.py --check` fails on a rule linking a superseded ADR or an
accepted ADR no rule links).

`docs/specs/` holds the as-is behavior spec recovered from the code: one OpenSpec-style `spec.md`
per capability, a `constitution.md` with [Muss]/[Impl]-marked cross-cutting rules, and generated
contracts (OpenAPI, data model, LLM tools). When a change alters behavior, update the affected spec
and rerun `python docs/specs/trace_specs.py` (coverage check of routes/tables/tools/pages); after new
routes, tables or LLM tools run `python docs/specs/export_contracts.py` first. CI enforces both
(`.github/workflows/specs.yml`: contracts must match the code, `trace_specs.py --check` must pass);
whether an existing requirement still describes changed behaviour is only checked in review.

## Agent workflow (GitHub)

Issues are the single backlog; `status:*` labels are the state machine
(inbox → triaged → planned → approved → in-progress → in-review). `@claude /grill` (async
Q&A that turns a vague idea into a spec with acceptance criteria), `@claude /triage`,
`@claude /plan` and the label `status:approved` drive `.github/workflows/claude.yml`; agent PRs
come from `agent/*` branches and get an automatic review (`claude-review.yml`). The prompts live in
`.github/claude/` — `common.md` holds the risk rule (`risk:high` + `needs-human` for auth, crypto,
device-write modules, the `tools.py` boundary, deploy and CI). Details: `docs/ai-workflow/README.md`.

## Git Workflow

- After every repository change, create a Conventional Commit and open a pull request.
- Check whether the change requires documentation updates (for example, `README.md`) and include
  them when needed.

`src/nav/config.ts` is the single source of the menu (areas, tabs, route → area) for the redesign
in `docs/redesign/`; `npm run build` runs `scripts/check-nav.ts`, which fails when a `<Route>` in
`App.tsx` has no entry there or a pre-redesign route lost its home. Add every new route to both.

Pages under `pages/` map roughly 1:1 to the entries in `nav/config.ts`; `App.tsx` always renders
`AppShell` after the gates and points each `<Route>` directly at its page component. Several pages are
admin-only both in the route guard (`isAdmin &&` around the `<Route>`) and on the corresponding
backend routes — when adding an admin-only page, gate both sides.
