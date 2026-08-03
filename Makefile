.PHONY: install dev lint typecheck test build backend-install frontend-install

install: backend-install frontend-install

backend-install:
	python -m pip install -r backend/requirements.lock
	python -m pip install --no-deps -e ./backend

frontend-install:
	npm --prefix frontend install

dev:
	python scripts/dev.py

lint:
	python -m ruff check backend scripts
	npm --prefix frontend run lint

typecheck:
	npm --prefix frontend run typecheck

test:
	python -m pytest backend
	npm --prefix frontend run test

build:
	npm --prefix frontend run build
