# HomeAtlas Ansible Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish immutable HomeAtlas container images and deploy them as a monitored HTTPS service through `ansible-docker.lan`.

**Architecture:** GitHub Actions produces separate GHCR backend and frontend images tagged with their full source commit SHA. The Ansible role deploys the pinned images through Portainer in host-network mode, persists state at `/opt/homeatlas`, and exposes the host-network frontend through a Traefik file-provider route.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, Docker Compose, Ansible, Portainer, Traefik, Uptime Kuma.

**Spec:** `docs/superpowers/specs/2026-09-18-homeatlas-ansible-deployment-design.md`

## Global Constraints

- Keep both HomeAtlas containers in `network_mode: host`; discovery must access the host LAN.
- Keep the backend bound to `127.0.0.1:${HOMEATLAS_API_PORT}` and never add a backend Traefik route.
- Publish and deploy only `sha-<40-character-commit>` image tags; do not use `latest` or branch tags.
- Persist `/data` at `/opt/homeatlas` with root-only host permissions.
- Do not put the generated HomeAtlas administrator password into Ansible Vault.
- Use the existing Portainer Git-stack and Uptime Kuma role patterns.

---

### Task 1: Publish Immutable HomeAtlas Images

**Files:**
- Create: `.github/workflows/publish-images.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: `ghcr.io/torstenamshove/homeatlas-backend:sha-${GITHUB_SHA}`.
- Produces: `ghcr.io/torstenamshove/homeatlas-frontend:sha-${GITHUB_SHA}`.
- Consumes: `backend/Dockerfile` and `frontend/Dockerfile` unchanged.

- [ ] **Step 1: Add a workflow that builds both contexts with commit-SHA tags**

```yaml
name: Publish container images

on:
  push:
    branches: [master]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  publish:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - image: homeatlas-backend
            context: ./backend
            file: ./backend/Dockerfile
            build_args: ""
          - image: homeatlas-frontend
            context: ./frontend
            file: ./frontend/Dockerfile
            build_args: |
              VITE_BUILD_SHA=${{ github.sha }}
              VITE_BUILD_TIME=${{ steps.build_metadata.outputs.time }}
    steps:
      - uses: actions/checkout@v4
      - id: build_metadata
        run: printf 'time=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/metadata-action@v5
        id: meta
        with:
          images: ghcr.io/${{ github.repository_owner }}/${{ matrix.image }}
          tags: type=sha,format=long
      - uses: docker/build-push-action@v6
        with:
          context: ${{ matrix.context }}
          file: ${{ matrix.file }}
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          build-args: ${{ matrix.build_args }}
```

- [ ] **Step 2: Document manual workflow dispatch and the required image-tag format**

```markdown
For the first Ansible deployment, start **Publish container images** in GitHub Actions on the desired commit. Use the generated `sha-<40-character-commit>` tag as `homeatlas_image_tag` in the Ansible command.
```

- [ ] **Step 3: Validate the local source inputs**

Run: `docker compose config --quiet && python3 -m compileall -q backend/app && (cd frontend && npm run build)`

Expected: exit status `0`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish-images.yml README.md docs/superpowers
git commit -m "ci: publish HomeAtlas images to GHCR"
```

### Task 2: Add the HomeAtlas Portainer Stack

**Files:**
- Create: `roles/stack_homeatlas/tasks/main.yml`
- Create: `roles/stack_homeatlas/files/compose.yaml`
- Create: `roles/stack_homeatlas/vars/main.yml`
- Modify: `playbook.yml`

**Interfaces:**
- Consumes: required Ansible extra variable `homeatlas_image_tag` matching `sha-[0-9a-f]{40}`.
- Produces: Docker containers `homeatlas_backend` and `homeatlas_frontend`.
- Produces: persistent host directory `/opt/homeatlas`.

- [ ] **Step 1: Require an immutable image tag and create protected persistent storage**

```yaml
- name: Assert HomeAtlas image tag is immutable
  ansible.builtin.assert:
    that:
      - homeatlas_image_tag is defined
      - homeatlas_image_tag is match('^sha-[0-9a-f]{40}$')
    fail_msg: >-
      Set homeatlas_image_tag to the sha-<40-character-commit> tag published
      by HomeAtlas' Publish container images workflow.

- name: Create HomeAtlas data directory
  ansible.builtin.file:
    path: /opt/homeatlas
    state: directory
    owner: root
    group: root
    mode: "0700"
```

- [ ] **Step 2: Define the two host-network services and their health checks**

```yaml
services:
  backend:
    image: ghcr.io/torstenamshove/homeatlas-backend:${homeatlas_image_tag}
    container_name: homeatlas_backend
    restart: unless-stopped
    network_mode: host
    volumes:
      - /opt/homeatlas:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - TZ=Europe/Berlin
      - HOMEATLAS_API_PORT=8281
      - HOMEATLAS_DB_PATH=/data/homeatlas.db
      - HOMEATLAS_KEY_PATH=/data/secret.key
      - HOMEATLAS_OUI_PATH=/data/oui.json
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8281/api/health')\""]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
  frontend:
    image: ghcr.io/torstenamshove/homeatlas-frontend:${homeatlas_image_tag}
    container_name: homeatlas_frontend
    restart: unless-stopped
    network_mode: host
    environment:
      - HOMEATLAS_PORT=8280
      - HOMEATLAS_API_PORT=8281
    depends_on:
      backend:
        condition: service_healthy
```

- [ ] **Step 3: Register stack monitoring and the playbook role**

```yaml
uptimekuma_scope: homeatlas
uptimekuma_maintenances: []
uptimekuma_monitors:
  - name: homeatlas backend
    type: docker
    docker_container: homeatlas_backend
    docker_host: docker.lan
    parent: Dienste
    tags: [container]
    notifications: [E-Mail]
  - name: homeatlas frontend
    type: docker
    docker_container: homeatlas_frontend
    docker_host: docker.lan
    parent: Dienste
    tags: [container]
    notifications: [E-Mail]
  - name: homeatlas http
    type: http
    url: https://homeatlas.malt10.de
    parent: Dienste
    tags: [http]
    notifications: [E-Mail]
    maxretries: 3
    expiry_notification: true
```

- [ ] **Step 4: Validate Ansible syntax**

Run: `ansible-playbook --syntax-check --vault-password-file /home/torsten/projects/ansible-docker.lan/.secret/docker playbook.yml`

Expected: `playbook: playbook.yml`.

- [ ] **Step 5: Commit**

```bash
git add playbook.yml roles/stack_homeatlas
git commit -m "feat: deploy HomeAtlas through Portainer"
```

### Task 3: Add HTTPS Routing and Operating Documentation

**Files:**
- Create: `roles/stack_traefik/files/dynamic/homeatlas.yml.j2`
- Modify: `README.md`

**Interfaces:**
- Consumes: frontend listener `http://192.168.42.20:8280` from Task 2.
- Produces: HTTPS service `https://homeatlas.malt10.de`.

- [ ] **Step 1: Add the Traefik file-provider router**

```yaml
http:
  routers:
    homeatlas:
      rule: "Host(`homeatlas.malt10.de`)"
      entrypoints:
        - websecure
      tls: true
      service: homeatlas
  services:
    homeatlas:
      loadBalancer:
        servers:
          - url: "http://192.168.42.20:8280"
```

- [ ] **Step 2: Document the required deployment order and backup unit**

```markdown
Publish the selected HomeAtlas source commit first, then deploy with:

ansible-playbook --vault-password-file .secret/docker playbook.yml -t traefik,uptimekuma,homeatlas -e homeatlas_image_tag=sha-<40-character-commit>

Back up `/opt/homeatlas` as one unit because the SQLite database and `secret.key` are required together.
```

- [ ] **Step 3: Validate Ansible syntax after all routing changes**

Run: `ansible-playbook --syntax-check --vault-password-file /home/torsten/projects/ansible-docker.lan/.secret/docker playbook.yml`

Expected: `playbook: playbook.yml`.

- [ ] **Step 4: Commit**

```bash
git add README.md roles/stack_traefik/files/dynamic/homeatlas.yml.j2
git commit -m "feat: route HomeAtlas through Traefik"
```
