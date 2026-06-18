SHELL := /bin/sh

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PIP := $(BIN)/pip
APP_MODULE := openclaw.main:app
COMPOSE ?= docker compose

.DEFAULT_GOAL := help

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "%-24s %s\n", $$1, $$2}'

venv: ## Create a virtual environment
	$(PYTHON) -m venv $(VENV)

env: ## Copy the example environment file if .env does not exist
	@if [ ! -f .env ]; then cp .env.example .env; fi

install: venv ## Install application dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -e .

install-dev: venv ## Install application and developer dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -e .[dev]

bootstrap: env install-dev playwright-install ## Prepare a local development environment

playwright-install: ## Install Chromium for Playwright
	$(BIN)/playwright install chromium

freework-smoke: ## Run the Free-Work Playwright smoke scraper (example: make freework-smoke ARGS="--headful --from-date 2026-05-01")
	$(BIN)/python -m openclaw.scrapers.freework $(ARGS)

lehibou-setup: ## One-time setup: open browser so you can solve the Cloudflare challenge and save the session cookie
	$(BIN)/python -m openclaw.scrapers.lehibou --setup

lehibou-smoke: ## Run the LeHibou Playwright smoke scraper (example: make lehibou-smoke ARGS="--from-date 2026-06-01")
	$(BIN)/python -m openclaw.scrapers.lehibou --headful $(ARGS)

freework-login: ## One-time login: open browser so you can log in to Free-Work and save the session
	$(BIN)/python -m openclaw.scrapers.freework_submitter --login --headful

freework-onboarding: ## One-time profile setup: open browser to complete your Free-Work profile (required before Postuler works)
	$(BIN)/python -m openclaw.scrapers.freework_submitter --onboarding --headful

freework-submit-test: ## Dry-run submission on a mission URL (example: make freework-submit-test URL="https://...")
	$(BIN)/python -m openclaw.scrapers.freework_submitter --mission-url $(URL) --dry-run --headful --slow-mo 800

db-up: ## Start local PostgreSQL + pgvector
	$(COMPOSE) up -d postgres

db-down: ## Stop the local PostgreSQL stack
	$(COMPOSE) down

db-shell: ## Open a psql shell into the local database
	docker exec -it openclaw-postgres psql -U openclaw -d openclaw

db-create-tables: ## Create all ORM tables directly (dev only, no migrations)
	$(BIN)/python -c "from openclaw.db.session import create_tables; create_tables(); print('Tables created.')"

db-migrate: ## Apply all Alembic migrations
	$(BIN)/alembic upgrade head

db-check: ## Check database connectivity
	$(BIN)/python -c "from openclaw.db.session import check_db_connection; ok = check_db_connection(); print('DB: connected' if ok else 'DB: UNREACHABLE'); exit(0 if ok else 1)"

monitor: ## Run the continuous monitor loop (scrape + alert every 15 min)
	$(BIN)/python -m openclaw.monitor

bot: ## Run the Telegram bot (polling)
	$(BIN)/python -m openclaw.bot.main

seed-examples: ## Load proposal examples from data/proposal_examples/ into the DB
	$(BIN)/python scripts/seed_examples.py

dev: ## Run the FastAPI app with reload
	$(BIN)/uvicorn $(APP_MODULE) --host 0.0.0.0 --port 8000 --reload

run: ## Run the FastAPI app without reload
	$(BIN)/uvicorn $(APP_MODULE) --host 0.0.0.0 --port 8000

format: ## Format the codebase with Ruff
	$(BIN)/ruff format .

lint: ## Lint the codebase with Ruff
	$(BIN)/ruff check .

test: ## Run the unit test suite
	$(BIN)/python -m unittest discover -s tests

smoke: ## Compile the package to catch syntax errors
	$(BIN)/python -m compileall openclaw tests

check: smoke test ## Run lightweight verification

check-env: ## Verify local environment (Python, .env, DB, Playwright) is ready for debugging
	$(BIN)/python scripts/check_env.py

debug: db-up db-create-tables dev ## Start DB, create tables, and run the API with reload (full local debug stack)
