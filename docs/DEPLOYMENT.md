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

Set `MINILOG_SETUP_TOKEN=` after step 3 and recreate the API container. Compose accepts the empty value after setup; an empty token cannot claim a fresh deployment.

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

Create a verified snapshot while the API is running:

```sh
docker compose exec api minilog-backup
```

The command prints the snapshot path under `/data/backups`. Copy it to encrypted storage controlled by the household.

Restore is an explicit offline maintenance operation:

1. Stop normal API service.
2. Validate the selected snapshot and preserve the current database under a unique recovery name.
3. Restore into a temporary path.
4. Run integrity and schema checks.
5. Atomically replace the database and restart readiness checks.

No restore overwrites the sole current database before a validated recovery copy exists. Scheduled backups and retention automation are deferred.

After stopping the API, restore a selected snapshot with a pre-restore recovery copy:

```sh
docker compose stop api
docker compose run --rm api minilog-restore --confirm-offline /data/backups/minilog-YYYYMMDDTHHMMSSZ.sqlite3
docker compose up -d api web
```

A lossless Minilog ZIP export can be restored through the same offline safety path:

```sh
docker compose stop api
docker compose run --rm api minilog-restore-export --confirm-offline /data/import/minilog-export.zip
docker compose up -d api web
```

The archive is fully checksum-validated, must match the running database revision, and still causes a verified pre-restore SQLite recovery copy to be made.

### Minilog ZIP format version 1

The ZIP is a private, lossless application export. Its root `manifest.json` contains:

- `format`: the fixed value `minilog-export`;
- `format_version`: currently `1`;
- `created_at`: the UTC export timestamp;
- `database_revision`: the exact Alembic revision required for restore; and
- `files`: every other archive member keyed by its canonical relative path, with its byte size and lowercase SHA-256 digest.

`data.json` contains the same format version and a complete row list for every portable domain table. Binary profile-picture derivatives are stored as `profile-pictures/<baby-id>.webp`; retained PiyoLog source files are stored as `import-sources/<import-batch-id>.txt`. Invitations, sessions, mutation receipts, and synchronization history are deliberately excluded and are reset during restore.

Restore accepts only the exact declared member set. It rejects malformed ZIPs, duplicate or unsafe paths, symbolic links, encrypted members, excessive member counts or expanded size, checksum mismatches, unknown versions, incomplete table sets, invalid columns, relationship violations, and database-revision mismatches. Validation and reconstruction happen in a temporary database; the live database is atomically replaced only after integrity checks pass.

## Upgrades

Images use explicit versions; automatic unattended application updates are not enabled. On every API start, `minilog-start` serves a temporary maintenance response, validates the current schema, and skips Alembic when the expected revision is already installed. An upgrade:

1. Pulls matching `web` and `api` versions.
2. Enters API maintenance mode.
3. Takes and verifies a pre-migration snapshot.
4. Applies Alembic migrations.
5. Runs database integrity and application readiness checks.
6. Starts the web container only against a compatible API.

Migration failure restores the verified snapshot before the container exits and leaves only a sanitized exception class in the lifecycle diagnostic. A failed first migration removes its incomplete database. The frontend polls the compatibility endpoint and shows maintenance or version-mismatch state rather than running against an incompatible contract.

## Recovery and lockout

A local API-container command can reset the Owner password or issue a new controlled recovery token. It requires direct server access, revokes sessions, never prints stored data, and is covered by recovery tests.

```sh
docker compose exec api minilog-reset-owner
```

## Operational checks

- Liveness reports process health only.
- Readiness checks expected schema, writable local storage, and a basic database query without exposing Household details.
- Logs follow [SECURITY.md](./SECURITY.md).
- No container requires outbound network access at runtime.
