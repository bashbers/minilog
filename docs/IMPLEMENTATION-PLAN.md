# Implementation plan

This plan orders work by dependency and risk. A phase is complete only when its tests and documentation pass; later phases do not paper over an unstable earlier seam.

## Phase 0: repository and contracts

- Initialize Git and add AGPL-3.0.
- Establish frontend, backend, generated-client, and Compose directories.
- Pin supported Node, Python, and package-manager versions.
- Add formatting, linting, type checking, unit-test commands, and a single local verification command.
- Encode OpenAPI generation and drift checking.
- Add a no-third-party-runtime-request browser test from the beginning.

Exit: empty frontend and API builds run through Compose on both target architectures, and CI-equivalent checks run locally.

## Phase 1: database, bootstrap, and access

- Implement SQLAlchemy mappings and the initial Alembic migration from [DATA-MODEL.md](./DATA-MODEL.md).
- Configure SQLite connections, transactions, WAL, foreign keys, and busy handling.
- Implement setup token, first Owner, Argon2id credentials, invitations, sessions, CSRF, device revocation, and server recovery command.
- Implement Household settings, Baby identity, and authorization policies.

Exit: setup and recovery cannot be raced or bypassed; role and session tests pass against real SQLite.

## Phase 2: typed care records

- Implement the common Care-record command/query model.
- Add detail tables, schemas, validators, and APIs one type at a time.
- Enforce active sleep, breastfeeding, and per-Caregiver pumping constraints.
- Implement expected-revision updates, tombstone deletion, attribution, pagination, and filters.
- Generate and consume the TypeScript API client.

Exit: every record type has database, domain, API-contract, and concurrency tests.

## Phase 3: dark-first mobile PWA

- Build the accessible visual primitives and selected-Baby shell.
- Add Today, quick-add bottom sheet, active records, and chronological list.
- Add profile-picture upload/crop/removal.
- Add History filters and Trends with daily, 7-day, and 30-day views.
- Add caregiver quick-action preferences and cross-Baby active indicators.

Exit: primary flows pass keyboard, screen-reader, contrast, reduced-motion, daylight-legibility, and mobile Playwright checks.

## Phase 4: synchronization and offline creation

- Add transactional change sequence, mutation idempotency, cursor pagination, tombstones, pruning, and full-resync rules.
- Add IndexedDB cache and durable pending queue.
- Synchronize every five seconds while visible and on launch, foreground, and reconnection.
- Add stale-revision UI, queued/failed state, safe retries, cache clearing, and controlled service-worker updates.

Exit: tests cover network loss before and after commit, duplicate retries, expired cursors, multiple devices, hidden tabs, reloads, and preserved pending writes.

## Phase 5: PiyoLog migration

- Create English and Japanese locale adapters with public, synthetic, and regression fixtures.
- Parse day and month exports without writes.
- Build preview, source-time-zone selection, type mapping, unknown preservation, daily-note preservation, and totals reconciliation.
- Add confirmation transaction, exact-file idempotency, provenance, retained-source deletion, revised-import replacement, and modified-record conflicts.

Exit: no malformed or unsupported line disappears silently, and import reports reconcile or require explicit acceptance.

## Phase 6: portability and destructive operations

- Define and document the versioned Minilog ZIP manifest.
- Implement checked export and transactional restore.
- Add formula-safe flattened CSV.
- Implement Caregiver identity erasure and Owner-confirmed Baby and Household deletion.
- Add safe manual SQLite backup and restore commands.

Exit: round-trip fixtures preserve all supported domain data and pictures; corruption, traversal, incompatible versions, partial restores, and deletion residue are tested.

## Phase 7: deployment hardening and release

- Produce non-root multi-stage `web` and `api` images for `amd64` and `arm64`.
- Add health checks, maintenance mode, version compatibility, restrictive filesystems, CSP, proxy configuration, and sanitized structured logging.
- Add verified pre-migration snapshots and failure rollback.
- Complete installation, HTTPS/VPN, upgrade, recovery, privacy, and limitation documentation.
- Run the full [PRODUCT.md](./PRODUCT.md) definition-of-done matrix.

Exit: a clean machine can install, use, upgrade, recover, export, restore, and remove Minilog solely from the published documentation.

## Cross-cutting test strategy

- Backend: Pytest service and API integration tests using real temporary SQLite databases.
- Frontend: component/unit tests for forms, renderers, summaries, and state transitions.
- Contract: generated TypeScript client must match committed OpenAPI.
- End to end: Playwright on mobile and desktop browser profiles.
- Accessibility: automated scans plus keyboard/focus and screen-reader-oriented assertions.
- Security: authorization matrix, CSRF, session fixation/revocation, parser limits, archive extraction, CSP, and log-redaction tests.
- Recovery: actual backup, migration failure, snapshot restoration, export round trip, and destructive deletion checks.
- Privacy: fail a browser test on any unexpected runtime origin.
