PYTHON ?= .venv/bin/python
API_PORT ?= 18000
DATASET ?= data/generated/train.json

.PHONY: test lint check-structure test-api lint-api run-api test-console lint-console build-console run-console smoke-skeleton migrate seed generate

test: check-structure test-api test-console

lint: lint-api lint-console

check-structure:
	python3 scripts/check_structure.py

test-api:
	PYTHONPATH=backend $(PYTHON) -m pytest backend/tests

lint-api:
	$(PYTHON) -m ruff check --config backend/pyproject.toml backend scripts

run-api:
	PYTHONPATH=backend $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $(API_PORT)

test-console:
	npm --prefix frontend run test

lint-console:
	npm --prefix frontend run lint

build-console:
	npm --prefix frontend run build

run-console:
	npm --prefix frontend run dev

smoke-skeleton:
	python3 scripts/smoke_skeleton.py

migrate:
	PYTHONPATH=backend $(PYTHON) -m app.data.cli migrate

seed:
	PYTHONPATH=backend $(PYTHON) -m app.data.cli seed --dataset $(DATASET)

generate:
	PYTHONPATH=backend $(PYTHON) -m app.data.cli generate
