# Release verification record

This file records observed results; it does not turn an untested architecture into a supported release target.

## 2026-09-13 development candidate

- Source commit: `e860bb6844b1e322d670504f63e950e5bf1da7de`.
- Runtime and host architecture: Podman 5.8.4 on `x86_64` (`amd64`).
- Repository gate: passed 46 backend tests, 45 frontend tests, type checking, production PWA build, and all 32 Chromium, Firefox, and mobile WebKit end-to-end flows in the pinned Playwright container.
- Compose: both source-built services healthy; only web port 8080 published; live/readiness, security-header, 2 MiB upload-proxy, enforced LAN-origin, and nginx sentinel-log checks passed; startup logs contained no setup-token reference.
- Image IDs: API `0929297e5510032841a218336b18d696744273f9a2e25a9a85a05ce3c1b45c04`; web `bcbb78baabd96e9ee9f5f0b9783d50a5d333e754efe24dbf17d7bf9938992d50`.
- `arm64`: base manifests resolved, but execution could not be tested because this host has no arm64 binfmt/QEMU support. The arm64 release gate remains open.
