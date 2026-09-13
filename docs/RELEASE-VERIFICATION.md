# Release verification record

This file records observed results; it does not turn an untested architecture into a supported release target.

## 2026-09-13 development candidate

- Source commit at the start of the run: `ec236386f02e60ee8f8b9b6bb0a8314e16e292b7` (later review fixes require a new final run).
- Host architecture: `x86_64` (`amd64`).
- Repository gate: passed 43 backend tests, 45 frontend tests, type checking, production PWA build, 24 Chromium/Firefox end-to-end flows, and 8 mobile WebKit flows.
- Compose: both source-built services healthy; only web port 8080 published; live/readiness and security-header checks passed; startup logs contained no setup-token reference.
- `arm64`: base manifests resolved, but execution could not be tested because this host has no arm64 binfmt/QEMU support. The arm64 release gate remains open.
