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

db-up: ## Start local PostgreSQL + pgvector
	$(COMPOSE) up -d postgres

db-down: ## Stop the local PostgreSQL stack
	$(COMPOSE) down

dev: ## Run the FastAPI app with reload
	$(BIN)/uvicorn $(APP_MODULE) --host 0.0.0.0 --port 8000 --reload

run: ## Run the FastAPI app without reload
	$(BIN)/uvicorn $(APP_MODULE) --host 0.0.0.0 --port 8000

format: ## Format the codebase with Ruff
	$(BIN)/ruff format .

lint: ## Lint the codebase with Ruff
	$(BIN)/ruff check .

test: ## Run the unit test suite
	$(PYTHON) -m unittest discover -s tests

smoke: ## Compile the package to catch syntax errors
	$(PYTHON) -m compileall openclaw

check: smoke test ## Run lightweight verification

