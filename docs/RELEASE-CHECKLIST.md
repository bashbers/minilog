# Release verification checklist

Run this checklist from a clean checkout of the exact release commit. Do not print or attach `.env`; it can contain the one-time setup token.

## Automated product matrix

| Product requirement | Verification evidence |
| --- | --- |
| All care types, typed validation, timers, revisions, and role boundaries | Backend integration suite in `make backend-test` |
| Offline creation, idempotent retry, foreground polling, cursor expiry, and browser cleanup | Frontend unit suite and Playwright flows in `make frontend-test` and `make frontend-e2e` |
| Mobile/desktop behavior, touch targets, keyboard use, contrast, reduced motion, and screen-reader-oriented semantics | Chromium, Firefox, and mobile WebKit projects in `make frontend-e2e` |
| No third-party runtime requests | Every primary Playwright test fails on an HTTP(S) or WebSocket origin other than the local Minilog test origin |
| PiyoLog preview/confirm, English/Japanese parsing, unknown-line preservation, reconciliation, and re-import conflicts | Backend PiyoLog integration suite |
| Lossless export/restore, corruption and traversal rejection, CSV neutralization, backups, failed migrations, and rollback | Backend export and recovery suites |
| Permanent Baby/Household deletion and Caregiver erasure, including SQLite sidecar and browser residue | Backend destructive-operation tests plus browser deletion flows |
| Generated frontend API contract and production PWA build | `make openapi`, a clean Git diff, `make frontend-build`, and service-worker Playwright coverage |

The complete repository gate requires Docker or Podman. All browser projects run inside the pinned Playwright container, so host browser binaries and system packages are not required:

```sh
make openapi
pnpm --dir frontend generate:api
git diff --exit-code -- frontend/openapi.json frontend/src/api/schema.d.ts
make verify
```

## Container and architecture matrix

Both Dockerfiles are multi-stage, use multi-architecture upstream images, and run their final process as a non-root user. Verify both target platforms on builders with native workers or configured binfmt/QEMU support:

```sh
docker buildx build --platform linux/amd64 --load -t minilog-api:release-amd64 backend
docker buildx build --platform linux/amd64 --load -t minilog-web:release-amd64 frontend
docker buildx build --platform linux/arm64 -t minilog-api:release-arm64 backend
docker buildx build --platform linux/arm64 -t minilog-web:release-arm64 frontend
```

An image merely building is insufficient. On each native target, perform the documented fresh-install and upgrade flow with a disposable named volume, confirm both services become healthy, complete setup, create one record of every type, exercise offline creation, export and restore, then remove the disposable volume. Record the exact commit, runtime versions, architecture, and result in [RELEASE-VERIFICATION.md](./RELEASE-VERIFICATION.md). Do not claim an architecture as supported until its native or emulated runtime matrix is recorded as passing.

## Live Compose acceptance

On the intended host:

```sh
docker compose up --build -d --force-recreate
docker compose ps
curl -fsS http://127.0.0.1:8080/api/v1/health/live
curl -fsS http://127.0.0.1:8080/api/v1/health/ready
curl -fsSI http://127.0.0.1:8080/
```

Confirm both services are healthy, only the web port is published, the API is reachable only through `/api`, security headers are present, no setup token appears in logs, and no runtime request leaves the configured origin. Preserve the production data volume during verification.

Run `frontend/scripts/compose-smoke.sh <configured-public-origin>` to check health, headers, and a request body above nginx's former 1 MiB default. Omitting the argument uses the example default `http://localhost:8080`. To verify proxy-log privacy with a harmless sentinel, stop `api`, request `/api/v1/health/ready?sentinel=MINILOG_LOG_PRIVACY_TEST`, confirm the sentinel is absent from `docker compose logs web`, then start `api` again. Never use real private data as a sentinel.

## Human recovery drill

Before release, an operator unfamiliar with the implementation follows [DEPLOYMENT.md](./DEPLOYMENT.md) without unpublished steps to:

1. install and claim a fresh deployment;
2. clear the setup token;
3. create and copy out a verified snapshot;
4. upgrade across a schema migration and observe maintenance/readiness;
5. recover from a deliberately failed migration;
6. restore both a SQLite snapshot and a Minilog ZIP;
7. reset Owner access from the server; and
8. remove the deployment and its disposable volume.

Any undocumented step or ambiguous destructive command blocks the release.
