# Minilog

Minilog is a privacy-first, self-hosted baby-care log designed for fast, one-handed use on mobile devices. The installable React PWA talks only to its same-origin FastAPI service; the service is the sole owner of a concrete SQLAlchemy/SQLite database.

It records breastfeeding, bottles, solid food, sleep, diapers, pumping, measurements, medication administrations, and notes. It also provides shared household accounts, foreground synchronization, offline creation, seven-day charts, profile pictures, English/Japanese PiyoLog text migration, and checked data export and recovery.

## Quick start with Docker Compose

Docker Engine with Compose v2 is the only runtime prerequisite.

```sh
cp .env.example .env
openssl rand -base64 32
```

Put the generated value in `.env` as `MINILOG_SETUP_TOKEN`, then run:

```sh
docker compose up --build -d
```

Open `http://localhost:8080`, enter the setup token, and create the first Owner. The SQLite database and application-managed recovery artifacts live only in the `minilog-data` volume.

For access beyond the local machine, place Minilog behind an HTTPS reverse proxy or a private VPN and set:

```dotenv
MINILOG_PUBLIC_ORIGIN=https://minilog.example.test
MINILOG_SECURE_COOKIES=true
```

Minilog deliberately does not provision DNS, certificates, port forwarding, hosted identity, or a cloud relay.

## Local development

Use Python 3.12 or 3.13 and Node.js 22+ with Corepack/pnpm:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
corepack pnpm --dir frontend install --frozen-lockfile
MINILOG_DATABASE_URL=sqlite:///./data/minilog.db .venv/bin/alembic -c backend/alembic.ini upgrade head
```

Run the API and PWA in separate terminals:

```sh
cd backend
MINILOG_SETUP_TOKEN=development-setup-token-change-me ../.venv/bin/uvicorn minilog.main:app --reload
```

```sh
cd frontend
VITE_API_TARGET=http://localhost:8000 corepack pnpm dev
```

Verify the repository with `make verify`. Regenerate the checked-in API contract after backend schema changes with `make openapi`, followed by `pnpm --dir frontend generate:api`.

## Migration, export, and recovery

PiyoLog migration is available to the Owner under Settings. Uploading an English or Japanese text export first produces a no-write preview. Confirmation preserves provenance and unknown lines; revised exports automatically replace unchanged imported records and require an explicit choice for locally corrected records.

Settings also provides a lossless, checksummed Minilog ZIP and a human-readable timeline CSV. Manual SQLite backup, checked restore, portable-export restore, and Owner-password recovery commands are documented in [Deployment](./docs/DEPLOYMENT.md).

## Privacy boundary

There are no ads, analytics, telemetry, remote fonts, CDN assets, vendor accounts, or third-party runtime requests. Session tokens are opaque and hashed at rest, passwords use Argon2id, mutations require CSRF validation, uploaded pictures are re-encoded with metadata removed, and request bodies never enter logs. See [Security](./docs/SECURITY.md) for the full threat model and operator responsibilities.

## Project documentation

- [Product contract](./docs/PRODUCT.md)
- [Architecture](./docs/ARCHITECTURE.md)
- [Concrete data model](./docs/DATA-MODEL.md)
- [Security and privacy model](./docs/SECURITY.md)
- [Deployment and recovery](./docs/DEPLOYMENT.md)
- [Implementation plan](./docs/IMPLEMENTATION-PLAN.md)
- [Nice-to-have backlog](./docs/NICE-TO-HAVE.md)
- [Domain language](./CONTEXT.md)
- [Architecture decisions](./docs/adr/)

Minilog is licensed under [AGPL-3.0-or-later](./LICENSE).
