# Deployment contract

This document is the operator runbook for the source-distributed Minilog release.

## Prerequisites and installation

Use a Linux host with either Docker Engine plus Compose v2 or Podman plus a Compose provider. The host filesystem holding the named volume must support normal SQLite file locks; do not place it on NFS, SMB, or another network filesystem.

From a checked-out Minilog release:

```sh
cp .env.example .env
chmod 600 .env
openssl rand -base64 32
```

Put the generated value in `.env` as `MINILOG_SETUP_TOKEN`. Set `MINILOG_PUBLIC_ORIGIN` to the exact origin caregivers will open, including a non-default port, and set the Household time zone. Then build and start both services:

```sh
docker compose up --build -d
docker compose ps
```

Podman users substitute `podman compose` in this entire guide. Wait for both services to report healthy, then open the configured origin. On the first screen, enter the setup token and create the Owner. Immediately clear `MINILOG_SETUP_TOKEN` in `.env` and recreate both services:

```sh
docker compose up -d --force-recreate api web
```

The token is not logged or persisted by Minilog. Keep `.env` out of backups that are shared with others. Do not expose an unclaimed installation to the internet.

## Compose services

The example `docker-compose.yml` contains:

1. `web`: serves the built PWA and proxies `/api` to the private API service.
2. `api`: runs one Uvicorn worker and owns all SQLite access, migrations, imports, exports, and image processing.
3. One named persistent volume mounted only by the API for the database, upgrade snapshots, and operator-requested export/backup output.

Only `web` publishes a host port. Both services run as non-root users, have health checks, use read-only container filesystems where practical, and receive only the capabilities and writable paths they need.

## Supported hosts

- Linux with Docker Engine and Compose
- `amd64`; `arm64` only for release candidates whose native/emulated result is recorded as passing in [RELEASE-VERIFICATION.md](./RELEASE-VERIFICATION.md)
- A local filesystem supported by SQLite locking

Network filesystems, shared volumes across API replicas, multiple Uvicorn workers, Kubernetes replicas, and active-active operation are unsupported.

## Required configuration

| Setting | Purpose |
| --- | --- |
| `MINILOG_PUBLIC_ORIGIN` | Exact accepted browser Host and Origin boundary |
| Household default time zone | Initial calendar grouping; editable by Owner |
| `MINILOG_SETUP_TOKEN` | One-time environment value that claims the first Owner safely |
| `MINILOG_SECURE_COOKIES` | Must be `true` exactly when the public origin uses HTTPS |
| Published local port | Defaults to local-network access |

Sessions and CSRF values are opaque random tokens whose hashes are stored in SQLite; Minilog has no signing-secret or Docker-secret setting. Configuration rejects an HTTPS origin without Secure cookies and rejects Secure cookies on an HTTP origin. Requests outside the configured Host/Origin boundary fail before routing, except the two internal health endpoints. Forwarded headers are stripped by nginx and ignored by Uvicorn.

## First run

1. The operator chooses a strong setup token and starts Compose.
2. Readiness waits for storage initialization and the expected schema.
3. The browser opens the setup screen and supplies the token while creating the Owner.
4. Minilog invalidates setup and the operator removes the token from active configuration.
5. The Owner creates the Household settings and first Baby.

Set `MINILOG_SETUP_TOKEN=` after step 3 and recreate both containers. Compose accepts the empty value after setup; an empty token cannot claim a fresh deployment.

The setup guide warns operators not to expose an unclaimed deployment publicly.

## Remote access

Compose exposes local HTTP for a trusted network. For access away from home, the operator uses either:

- A private VPN that reaches the local origin, or
- An HTTPS reverse proxy with a valid certificate.

Minilog does not provision DNS, certificates, port forwarding, or a hosted relay. Proxy examples must preserve the same origin for the PWA and `/api` and must not add analytics or remote assets.

Browser installation and service workers require a secure context. `http://localhost` qualifies, but a phone opening a plain LAN address such as `http://192.168.x.x:8080` generally does not. Plain LAN HTTP remains suitable for temporary testing, not for relying on offline creation or installation.

### HTTPS reverse proxy example

Bind Minilog to the host loopback interface by setting this additional value in `.env`:

```dotenv
MINILOG_PORT=127.0.0.1:8080
MINILOG_PUBLIC_ORIGIN=https://minilog.example.com
MINILOG_SECURE_COOKIES=true
```

A host-managed Caddy instance can terminate TLS and forward the whole origin without splitting the API onto another domain:

```caddyfile
minilog.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Use a valid certificate and restrict DNS/firewall exposure to the intended caregivers. Minilog starts Uvicorn with proxy-header trust disabled; security decisions do not depend on client-supplied forwarded headers. The configured `MINILOG_PUBLIC_ORIGIN` is enforced against the browser-visible Host and any supplied Origin header.

### Private VPN

Alternatively, connect caregivers to the home network with an operator-managed WireGuard-compatible VPN. Bind `MINILOG_PORT` to the VPN interface address or restrict port 8080 to that interface with the host firewall. HTTPS is still recommended for consistent PWA behavior; the VPN protects transport but does not automatically make a non-local HTTP URL a browser secure context.

## Data directory

The data volume contains the SQLite database and application-managed recovery artifacts. SQLite runs with foreign keys, secure deletion, WAL, and a bounded busy timeout. Online backups take a shared maintenance lock; privacy-sensitive mutations take the matching exclusive lock and establish SQLite exclusivity before changing data. Permanent application deletions truncate checkpointed WAL pages before reporting success, and a competing unmanaged reader causes a retryable response before the change commits. The API is the sole database owner; operators do not mount the live database into unrelated containers.

## Manual backup and restore

The MVP exposes an API-container command that uses SQLite's online backup mechanism, verifies integrity, and writes a timestamped snapshot with restrictive permissions. Copying that snapshot to independent storage is the operator's responsibility.

Create a verified snapshot while the API is running:

```sh
docker compose exec api minilog-backup
```

The command prints the snapshot path under `/data/backups`. Copy it to encrypted storage controlled by the household.

For example, replace `<printed-filename>` with the basename printed above:

```sh
mkdir -p ./private-minilog-backups
chmod 700 ./private-minilog-backups
docker compose cp api:/data/backups/<printed-filename> ./private-minilog-backups/<printed-filename>
chmod 600 ./private-minilog-backups/<printed-filename>
docker compose exec -T api sha256sum /data/backups/<printed-filename>
sha256sum ./private-minilog-backups/<printed-filename>
```

The two SHA-256 values must match before the copy is moved to encrypted off-host storage. With Podman, obtain the container ID using `podman compose ps -q api`, then use `podman cp <container-id>:/data/backups/<printed-filename> ./private-minilog-backups/<printed-filename>`; the permission and checksum commands are unchanged.

Restore is an explicit offline maintenance operation:

1. Stop normal API service.
2. Validate the selected snapshot and preserve the current database under a unique recovery name.
3. Restore into a temporary path.
4. Run integrity and schema checks.
5. Atomically replace the database and restart readiness checks.

No restore overwrites the sole current database before a validated recovery copy exists. Scheduled backups and retention automation are deferred.

Copy the printed backup file out of the named volume to encrypted, independently managed storage. To restore a selected snapshot, bind-mount the directory containing it read-only into the one-off container. Use an absolute host path in place of `/srv/private/minilog-recovery`:

```sh
docker compose stop api
docker compose run --rm -v /srv/private/minilog-recovery:/restore:ro api minilog-restore --confirm-offline /restore/minilog-YYYYMMDDTHHMMSSZ.sqlite3
docker compose up -d api web
docker compose ps
```

A lossless Minilog ZIP export can be restored through the same offline safety path:

```sh
docker compose stop api
docker compose run --rm -v /srv/private/minilog-recovery:/restore:ro api minilog-restore-export --confirm-offline /restore/minilog-export.zip
docker compose up -d api web
docker compose ps
```

The archive is fully checksum-validated, must match the running database revision, and still causes a verified pre-restore SQLite recovery copy to be made.

### Minilog ZIP format version 2

The ZIP is a private, lossless application export. On restore, static profile pictures are decoded and re-encoded as metadata-free lossless WebP: displayed RGB pixels are preserved exactly, while compression-container bytes and their content hash may change to ensure hidden payloads cannot survive. Its root `manifest.json` contains:

- `format`: the fixed value `minilog-export`;
- `format_version`: currently `2`;
- `created_at`: the UTC export timestamp;
- `database_revision`: the exact Alembic revision required for restore; and
- `files`: every other archive member keyed by its canonical relative path, with its byte size and lowercase SHA-256 digest.

`data.json` contains the same format version and a complete row list for every portable domain table. Each import-batch row explicitly records whether its source was retained. Binary profile-picture derivatives are stored as `profile-pictures/<baby-id>.webp`; retained PiyoLog source files are stored as `import-sources/<import-batch-id>.txt`. Invitations, sessions, mutation receipts, and synchronization history are deliberately excluded and are reset during restore.

Restore accepts only the exact declared member set. It rejects oversized or malformed ZIPs, duplicate or unsafe paths, symbolic links, encrypted members, excessive member counts or expanded size, checksum mismatches, unknown versions, incomplete table sets, invalid columns, relationship or domain-invariant violations, invalid binary derivatives or retained source text, Owner lockout, and database-revision mismatches. Validation and reconstruction happen in a temporary database; the live database is atomically replaced only after integrity checks pass.

## Upgrades

Images are built from the reviewed source checkout; automatic unattended application updates are not enabled. The frontend dependency graph is locked and the containerized Python graph is constrained to exact versions. Upstream base-image tags are not digest-pinned, so record the built image IDs and do not rebuild an already accepted release without repeating the release checks. On every API start, `minilog-start` serves a temporary maintenance response, validates the current schema, and skips Alembic when the expected revision is already installed. An upgrade:

1. Pulls matching `web` and `api` versions.
2. Enters API maintenance mode.
3. Takes and verifies a pre-migration snapshot.
4. Applies Alembic migrations.
5. Runs database integrity and application readiness checks.
6. Starts the web container only against a compatible API.

Migration failure restores the verified snapshot and keeps the API in maintenance mode so the restart policy cannot repeat the migration or create unbounded snapshots. It logs only a sanitized exception class and an operator-action marker. A failed first migration removes its incomplete database. The frontend polls the compatibility endpoint and shows maintenance or version-mismatch state rather than running against an incompatible contract.

For the source-distributed release, upgrade from a clean checkout while preserving the existing `.env` and named volume:

```sh
docker compose exec api minilog-backup
git fetch --tags
git checkout <reviewed-release-tag>
docker compose build
docker compose up -d
docker compose ps
```

Read the release notes before choosing the tag. Do not run `docker compose down --volumes` during an upgrade. Startup takes and verifies an additional pre-migration snapshot automatically whenever the schema revision changes. If the API fails to become healthy, it remains in maintenance without retrying the migration. Run `docker compose stop api`, inspect the sanitized lifecycle log, and follow the offline restore procedure above.

## Recovery and lockout

A local API-container command can reset the Owner password. It requires direct server access, revokes sessions, never prints stored data, and is covered by recovery tests.

```sh
docker compose exec api minilog-reset-owner
```

## Operational checks

- Liveness reports process health only.
- Readiness checks expected schema, writable local storage, and a basic database query without exposing Household details.
- Logs follow [SECURITY.md](./SECURITY.md).
- No container requires outbound network access at runtime.

The production web response should include Content Security Policy, Permissions Policy, MIME-sniffing, framing, referrer, and cross-origin isolation headers. Verify the same origin and API proxy after installation:

```sh
curl -fsSI http://127.0.0.1:8080/
curl -fsS http://127.0.0.1:8080/api/v1/health/ready
frontend/scripts/compose-smoke.sh http://127.0.0.1:8080
```

The readiness response contains no Household data. API access logs are disabled at the server; Minilog emits only allowlisted structured request and lifecycle fields described in [SECURITY.md](./SECURITY.md).

## Removing Minilog

First create and copy out any export or backup the Household wants to keep. Then stop the stack. The following final command permanently removes the named data volume and all live Minilog data on this host:

```sh
docker compose down
docker compose down --volumes
```

This does not erase copies already placed in backups, exports, filesystem snapshots, browser storage on other devices, or storage media remapping. Remove those separately according to the operator's retention policy.

## Known deployment limitations

- One API process and one SQLite database are supported; do not scale the API service or share its volume.
- Network filesystems, Kubernetes replicas, active-active failover, and unattended automatic upgrades are unsupported.
- Minilog does not manage DNS, certificates, VPN accounts, host encryption, firewalls, off-host backup retention, or monitoring.
- Application data is not encrypted inside SQLite. Use encrypted host storage and encrypt every exported copy.
- Plain LAN HTTP is not a dependable installable/offline PWA origin on phones.
- Source-built release images are not byte-reproducible because upstream base-image tags are not digest-pinned; every rebuilt image requires the release matrix and recorded image IDs.
- Browser and filesystem deletion cannot guarantee erasure from device snapshots, flash wear-leveling, or copies outside Minilog's control.

The release verification matrix is maintained in [RELEASE-CHECKLIST.md](./RELEASE-CHECKLIST.md).
