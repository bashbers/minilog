.PHONY: install verify contract backend-test frontend-test frontend-build frontend-e2e openapi

install:
	cd backend && ../.venv/bin/python -m pip install -e '.[dev]'
	cd frontend && pnpm install --frozen-lockfile

verify: contract backend-test frontend-test frontend-build frontend-e2e

contract:
	contract_dir=$$(mktemp -d); \
	trap 'rm -rf "$$contract_dir"' EXIT; \
	cd backend; \
	../.venv/bin/python scripts/export_openapi.py "$$contract_dir/openapi.json"; \
	cd ../frontend; \
	./node_modules/.bin/openapi-typescript "$$contract_dir/openapi.json" -o "$$contract_dir/schema.d.ts"; \
	diff -u openapi.json "$$contract_dir/openapi.json"; \
	diff -u src/api/schema.d.ts "$$contract_dir/schema.d.ts"

backend-test:
	cd backend && ../.venv/bin/ruff check src tests
	cd backend && ../.venv/bin/pytest

frontend-test:
	cd frontend && pnpm test -- --run

frontend-build:
	cd frontend && pnpm typecheck
	cd frontend && pnpm build

frontend-e2e:
	cd frontend && pnpm test:e2e

openapi:
	cd backend && ../.venv/bin/python scripts/export_openapi.py ../frontend/openapi.json
