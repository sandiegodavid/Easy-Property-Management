# Local Containerized Hosting Test Environment (Admin + Operator)

Runs interactive local Docker containers for **Admin** and **Operator** with their real compiled React UIs, real FastAPI routers, and schema-validated SQLite stores (`admin.sqlite`, `hosted-access.sqlite`, `property-management.sqlite`), while intentionally skipping other hosting services (Caddy, Cloudflare Tunnel, Firebase, `epm-backup-proxy`, `epm-egress-proxy`, `epm-host-guardian`, and Ops Agent).

> **Test-only environment:** Production builds and host deployments continue to use `Dockerfile.admin`, `Dockerfile.operator`, `shared_identity_entry.py`, and `operator_entry.py`.

## Prerequisites

1. Docker Desktop running.
2. Compiled frontend bundles present (rebuild whenever frontend code changes):
   ```bash
   cd application
   npm run build && npm run build:admin && npm run build:central
   ```

## Quick Start

Run from `application/`:

```bash
# Build and start Admin + Operator containers
docker compose -f deploy/hosted-mvp/local-test/compose.yaml up -d --build

# Check container health
docker compose -f deploy/hosted-mvp/local-test/compose.yaml ps
```

### Local URLs

| Container | URL | What It Runs |
| --- | --- | --- |
| **Admin** (`epm-local-admin`) | http://localhost:18801 | Real Admin-lite UI & APIs backed by `admin.sqlite` (Free v1 policy, capacity snapshot, seeded `demo` operator) |
| **Operator** (`epm-local-operator`) | http://localhost:18802 | Real Operator UI & APIs backed by `hosted-access.sqlite` + synthetic `demo/seed.py` business workspace |

### Local Auth Helper Routes

By default (`EPM_LOCAL_AUTO_LOGIN=1`), visiting `/` automatically mints a real SQLite-backed session cookie and loads the authenticated UI.

- `GET /__local__/sign-in` — Mint a fresh real session cookie and redirect to `/`.
- `GET /__local__/sign-out` — Revoke the current session cookie and redirect to `/?signed_out=1` (to inspect the signed-out screen).
- `GET /__local__/status` — Inspect container status, IDs, and session state.
- `GET /health/live` and `GET /health/ready` — Health endpoints.

Set `EPM_LOCAL_AUTO_LOGIN=0` to start unauthenticated and sign in manually via `/__local__/sign-in`.

## Stop & Reset

```bash
# Stop containers (keeps seeded SQLite volumes)
docker compose -f deploy/hosted-mvp/local-test/compose.yaml down

# Stop containers and wipe volumes to re-seed from scratch
docker compose -f deploy/hosted-mvp/local-test/compose.yaml down -v
```
