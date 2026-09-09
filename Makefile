.PHONY: install verify backend-test frontend-test frontend-build openapi

install:
	cd backend && ../.venv/bin/python -m pip install -e '.[dev]'
	cd frontend && pnpm install --frozen-lockfile

verify: backend-test frontend-test frontend-build

backend-test:
	cd backend && ../.venv/bin/ruff check src tests
	cd backend && ../.venv/bin/pytest

frontend-test:
	cd frontend && pnpm test -- --run

frontend-build:
	cd frontend && pnpm typecheck
	cd frontend && pnpm build

openapi:
	cd backend && ../.venv/bin/python scripts/export_openapi.py ../frontend/openapi.json

