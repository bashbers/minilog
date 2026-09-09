# Deployment contract

This document defines the deployment the implementation must provide. Exact image names and commands will be filled in when code exists.

## Compose services

The example `docker-compose.yml` contains:

1. `web`: serves the built PWA and proxies `/api` to the private API service.
2. `api`: runs one Uvicorn worker and owns all SQLite access, migrations, imports, exports, and image processing.
3. One named persistent volume mounted only by the API for the database, upgrade snapshots, and operator-requested export/backup output.

Only `web` publishes a host port. Both services run as non-root users, have health checks, use read-only container filesystems where practical, and receive only the capabilities and writable paths they need.

## Supported hosts

- Linux with Docker Engine and Compose
- `amd64` and `arm64`
- A local filesystem supported by SQLite locking

Network filesystems, shared volumes across API replicas, multiple Uvicorn workers, Kubernetes replicas, and active-active operation are unsupported.

## Required configuration

| Setting | Purpose |
| --- | --- |
| Public origin | Cookie, CSRF, and generated-link boundary |
| Household default time zone | Initial calendar grouping; editable by Owner |
| One-time setup token or Docker secret | Claims the first Owner safely |
| Trusted proxy configuration | Enables forwarded headers only behind known proxies |
| Published local port | Defaults to local-network access |

An application session-signing secret is generated with cryptographic randomness and persisted inside the protected data volume if not explicitly supplied. It is never printed. Configuration validation fails closed on unsafe or contradictory production settings.

## First run

1. The operator chooses a strong setup token and starts Compose.
2. Readiness waits for storage initialization and the expected schema.
3. The browser opens the setup screen and supplies the token while creating the Owner.
4. Minilog invalidates setup and the operator removes the token from active configuration.
5. The Owner creates the Household settings and first Baby.

The setup guide warns operators not to expose an unclaimed deployment publicly.

## Remote access

Compose exposes local HTTP for a trusted network. For access away from home, the operator uses either:

- A private VPN that reaches the local origin, or
- An HTTPS reverse proxy with a valid certificate.

Minilog does not provision DNS, certificates, port forwarding, or a hosted relay. Proxy examples must preserve the same origin for the PWA and `/api` and must not add analytics or remote assets.

## Data directory

The data volume contains the SQLite database and application-managed recovery artifacts. SQLite runs with foreign keys, WAL, and a bounded busy timeout. The API is the sole database owner; operators do not mount the live database into unrelated containers.

## Manual backup and restore

The MVP exposes an API-container command that uses SQLite's online backup mechanism, verifies integrity, and writes a timestamped snapshot with restrictive permissions. Copying that snapshot to independent storage is the operator's responsibility.

Restore is an explicit offline maintenance operation:

1. Stop normal API service.
2. Validate the selected snapshot and preserve the current database under a unique recovery name.
3. Restore into a temporary path.
4. Run integrity and schema checks.
5. Atomically replace the database and restart readiness checks.

No restore overwrites the sole current database before a validated recovery copy exists. Scheduled backups and retention automation are deferred.

## Upgrades

Images use explicit versions; automatic unattended application updates are not enabled. An upgrade:

1. Pulls matching `web` and `api` versions.
2. Enters API maintenance mode.
3. Takes and verifies a pre-migration snapshot.
4. Applies Alembic migrations.
5. Runs database integrity and application readiness checks.
6. Starts the web container only against a compatible API.

Migration failure restores the verified snapshot and leaves a sanitized diagnostic. The frontend checks API compatibility and shows maintenance or version-mismatch state rather than running against an incompatible contract.

## Recovery and lockout

A local API-container command can reset the Owner password or issue a new controlled recovery token. It requires direct server access, revokes sessions, never prints stored data, and is covered by recovery tests.

## Operational checks

- Liveness reports process health only.
- Readiness checks expected schema, writable local storage, and a basic database query without exposing Household details.
- Logs follow [SECURITY.md](./SECURITY.md).
- No container requires outbound network access at runtime.
