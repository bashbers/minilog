# Minilog architecture

## System shape

```text
Installed PWA / browser
        |
        | same-origin HTTP; HTTPS supplied by operator for remote access
        v
Frontend container
  static assets + /api reverse proxy
        |
        | private Compose network
        v
FastAPI container  --->  SQLite + profile images/import sources/backups
 one Uvicorn worker       persistent Docker volume
```

Only the frontend port is published. The API and persistent volume are private to the Compose deployment. The application runs as one instance against a local filesystem; network-mounted SQLite and clustered API replicas are unsupported.

## Technology baseline

### Frontend

- React and TypeScript built with Vite
- React Router for Today, History, Trends, and administration routes
- TanStack Query for server state
- IndexedDB for the seven-day cache, synchronization cursor, and pending creations
- A service worker for installation, local application assets, and controlled updates
- TypeScript request and response types generated from FastAPI's OpenAPI document

Route-level care screens live under `features/care`; `App` owns session gating, Baby selection, and the application shell. Reusable visual units live under `components`. Care-record types register their form, renderer, summary contribution, and API schema mapping through one explicit registry. Shared primitives provide dark-first controls, bottom sheets, touch targets, charts, conflict messages, and accessible form behaviour.

### Backend

- FastAPI with Pydantic request and response models
- SQLAlchemy 2 declarative mappings and transaction boundaries
- Alembic migrations
- SQLite configured with foreign keys, WAL, and a busy timeout
- One Uvicorn worker

Backend modules use a deliberately small layered structure:

- `models` and `schemas` define relational persistence and the HTTP/domain vocabulary;
- `services` own multi-step care-record, synchronization, import/export, and destructive privacy operations;
- `api` owns routing, authorization dependencies, and simple resource CRUD transactions; shared
  services may raise the same stable HTTP errors used by those routes to avoid duplicate adapters; and
- `cli`, migrations, and database helpers own offline lifecycle and recovery operations.

Complex invariants and privacy-sensitive transactions belong in services. Keeping straightforward single-resource CRUD in a route avoids repository and command wrappers that would only delegate.

## HTTP contract

All application endpoints live under `/api/v1`. The frontend and API use the same public origin, avoiding a cross-origin production configuration.

The initial resource surface is:

- `/setup` for guarded first-Owner creation
- `/sessions`, `/sessions/devices`, and `/invitations`
- `/household` and `/caregivers`
- `/babies` and `/babies/{id}/profile-picture`
- `/care-records` plus type-specific create/update representations
- `/sync` for cursor pulls and idempotent mutation pushes
- `/summaries/daily` and `/trends`
- `/imports/piyolog` for upload, preview, confirmation, conflict resolution, and source deletion
- `/exports/minilog` and `/exports/timeline.csv`
- `/health/live` and `/health/ready`

Commands use explicit request models and return the resulting entity revision. Updates and deletes require the caller's expected revision. Validation errors, authorization failures, stale revisions, expired cursors, and domain conflicts have stable machine-readable error codes.

## Authentication and authorization

The first Owner can be created only with a one-time setup token supplied through an environment variable. Once an Owner exists, normal HTTP setup is disabled. A server-side recovery command can deliberately reset the Owner password.

The Owner issues one-use, 24-hour invitation codes. Caregivers choose a local username and password; Minilog has no email dependency or external identity provider. Passwords use Argon2id.

Authentication uses random, opaque server sessions. Only a hash is stored in SQLite; the browser receives a `Secure`, `HttpOnly`, `SameSite` cookie. State-changing requests require CSRF protection. Sessions have a 30-day sliding lifetime, are visible as devices, and can be revoked individually. A password change revokes every other session.

Permissions are enforced at the API dependency boundary for every command and query, with privacy-sensitive destructive services repeating the relevant invariants. Frontend visibility is never the authorization boundary.

## Care-record extensibility

Every care-record type consists of:

1. A discriminator and shared row in `care_records`.
2. A one-to-one type-specific relational detail row.
3. Pydantic command and response schemas.
4. A domain validator.
5. A frontend form, renderer, and summary adapter.
6. Export and, where applicable, PiyoLog-import mappings.
7. Database, API-contract, frontend, and end-to-end tests.

Adding a built-in type is an explicit migration and registry change. Arbitrary JSON payloads and Household-defined schemas are not part of the MVP.

## Synchronization

### Server change stream

Every committed synchronization-relevant change appends a row to one monotonic `sync_changes` sequence in the same transaction. Pull requests ask for changes after a cursor and receive an ordered page plus the next cursor.

The visible PWA polls every five seconds. It also synchronizes on launch, reconnection, and return to the foreground, and pauses polling while hidden. Responses merge by entity ID and revision. There is no SSE or WebSocket channel.

Deletion changes are retained as tombstones for 30 days. The server publishes the oldest valid cursor; older clients must perform a full cache refresh before sending their preserved pending creations.

### Offline creation

The client creates UUIDs for new care records and mutations, validates locally, and stores the command durably in IndexedDB before presenting it as queued. The server records mutation IDs and returns the original result for a retry, making network uncertainty safe.

Only creation is available offline. Updates and deletes require a current server revision and connectivity. A `409` stale-revision response carries the current entity so the interface can show an explicit conflict.

### Application updates

The service worker downloads new application assets without forcing a reload. The PWA prompts the Caregiver and reloads only after queued writes synchronize and the user accepts. Active timed records remain on the server and survive a frontend update.

## Profile-picture processing

Uploads accept JPEG, PNG, and WebP with bounded byte and pixel sizes. The backend decodes the image, applies orientation, strips metadata, center-crops or applies the user-selected square crop, and stores only a small WebP derivative. Decoding occurs with resource limits. Replacement and removal delete the old derivative in the same logical operation.

## PiyoLog import pipeline

Locale adapters turn English or Japanese day/month text into a neutral parsed representation. Parsing never writes domain data. Preview performs validation, type mapping, date/time interpretation, daily-total reconciliation, duplicate detection, and conflict discovery.

Confirmation writes an immutable Import batch and its records in one transaction. Exact-file hashes prevent duplicate confirmation. Recognized records use normal typed tables and retain batch and source-line provenance. Unknown entries and date-only daily notes use dedicated read-only representations.

Edits to recognized imported records mark them modified since import. A revised import can automatically replace only unmodified records created by the superseded batch. Every other overlap requires an explicit decision.

## Exports

The authoritative ZIP export uses a documented, versioned manifest and checksums. Import validates the whole archive and schema version before changing data. Restore runs transactionally and never partially combines an incompatible archive with existing Household data.

CSV is a stable, flattened view intended for people and analytical tools. It is not accepted by the restore endpoint.

## Database lifecycle

Alembic is the sole schema-change mechanism. Startup validates the schema revision and refuses unknown or newer schemas. Upgrade mode stops normal requests, takes and verifies a SQLite snapshot, runs migrations, verifies integrity, and restores the snapshot if migration fails.

Scheduled backup automation is deferred. The MVP supplies a safe online snapshot command, a restore command, JSON/ZIP export, and documented volume handling.

## Privacy-preserving operations

- All JavaScript, styles, fonts, icons, and other runtime assets are bundled.
- A restrictive Content Security Policy prevents accidental remote loading.
- There is no telemetry, crash reporting, hosted authentication, CDN, or external update check.
- Logs contain request IDs, routes, status, timing, lifecycle events, sanitized failures, and authentication security events only.
- Care data, Baby and Caregiver names, notes, medicine names, images, credentials, tokens, and import contents never enter logs.

## Supported environment

Release images target Linux `amd64` and `arm64`. The UI supports the current and previous two major versions of Safari, Chrome, Firefox, and Edge, with iPhone and Android phone layouts as the primary experiences.
