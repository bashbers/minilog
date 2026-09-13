#!/bin/sh
set -eu

origin=${1:-http://localhost:8080}

curl -fsS "$origin/api/v1/health/live" >/dev/null
curl -fsS "$origin/api/v1/health/ready" >/dev/null
headers=$(curl -fsSI "$origin/")
printf '%s' "$headers" | grep -qi '^Content-Security-Policy:'
printf '%s' "$headers" | grep -qi '^Permissions-Policy:'
printf '%s' "$headers" | grep -qi '^X-Content-Type-Options: nosniff'

status=$(
  head -c 2097152 /dev/zero |
    curl -sS -o /dev/null -w '%{http_code}' -X POST \
      -H 'Content-Type: application/octet-stream' --data-binary @- \
      "$origin/api/v1/imports/piyolog/preview"
)
if [ "$status" != 401 ]; then
  echo "unexpected upload proxy status: $status" >&2
  exit 1
fi

echo "Compose health, headers, and upload proxy checks passed."
