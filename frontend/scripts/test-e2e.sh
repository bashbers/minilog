#!/bin/sh
set -eu

image="mcr.microsoft.com/playwright:v1.63.0-noble"
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)

pnpm build

if command -v podman >/dev/null 2>&1; then
  podman image exists "$image" || podman pull "$image"
  podman run --rm --network host --ipc=host --userns=keep-id \
    -v "$project_root:/work" -w /work/frontend "$image" \
    node_modules/.bin/playwright test
elif command -v docker >/dev/null 2>&1; then
  docker image inspect "$image" >/dev/null 2>&1 || docker pull "$image"
  docker run --rm --network host --ipc=host \
    --user "$(id -u):$(id -g)" -v "$project_root:/work" -w /work/frontend "$image" \
    node_modules/.bin/playwright test
else
  echo "Browser verification requires Podman or Docker." >&2
  exit 1
fi
