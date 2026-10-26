.PHONY: help install train test lint typecheck up down seed api web tf-validate openapi

PY ?= python3

help:  ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install:  ## Install Python (backend + ml) and frontend dependencies
	$(PY) -m pip install -r backend/requirements-dev.txt -e "ml[plots]"
	cd frontend && npm ci

train:  ## Train all models on synthetic data and regenerate the evaluation report
	$(PY) -m sentinel_ml.pipelines.train_all --out ml/artifacts --report docs/model-evaluation-report.md

test:  ## Run backend, ML and pipeline tests
	$(PY) -m pytest

lint:  ## Lint Python and TypeScript
	cd backend && ruff check .
	ruff check ml airflow tests infrastructure/lambda
	cd frontend && npm run lint

typecheck:  ## TypeScript type check
	cd frontend && npm run typecheck

up:  ## Start the full local stack (db, api, web)
	docker compose up --build

down:  ## Stop the local stack
	docker compose down

seed:  ## Create schema in a local SQLite DB and seed demo data (no Docker needed)
	cd backend && SENTINEL_DATABASE_URL=sqlite+aiosqlite:///./sentinel.db $(PY) -m app.db.seed --create-schema --scan

api:  ## Run the API against the local SQLite DB
	cd backend && SENTINEL_DATABASE_URL=sqlite+aiosqlite:///./sentinel.db uvicorn app.main:app --reload --port 8000

web:  ## Run the web app in dev mode
	cd frontend && API_INTERNAL_URL=http://localhost:8000 npm run dev

openapi:  ## Export the OpenAPI specification to docs/api/openapi.json
	cd backend && SENTINEL_DATABASE_URL=sqlite+aiosqlite:///:memory: $(PY) -c "import json,app.main as m; print(json.dumps(m.app.openapi(), indent=2))" > ../docs/api/openapi.json

tf-validate:  ## terraform fmt + validate for all environments
	cd infrastructure/terraform && terraform fmt -check -recursive
	for env in dev prod; do (cd infrastructure/terraform/environments/$$env && terraform init -backend=false -input=false >/dev/null && terraform validate); done
