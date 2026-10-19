.PHONY: install dev lint typecheck test build backend-install frontend-install api-types

PYTHON ?= python

install: backend-install frontend-install

backend-install:
	$(PYTHON) -m pip install -e "./backend[dev]" -c backend/requirements.lock

frontend-install:
	npm --prefix frontend ci

dev:
	$(PYTHON) scripts/dev.py

lint:
	$(PYTHON) -m ruff check backend scripts notebooks
	$(PYTHON) -m ruff format --check backend scripts notebooks
	npm --prefix frontend run lint

# Regenerate frontend/src/api/schema.gen.ts after changing an API model
api-types:
	$(PYTHON) scripts/generate_api_types.py

typecheck:
	$(PYTHON) scripts/generate_api_types.py --check
	npm --prefix frontend run typecheck

test:
	$(PYTHON) -m pytest backend
	npm --prefix frontend run test

build:
	npm --prefix frontend run build
