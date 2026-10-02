PYTHON ?= .venv/bin/python

.PHONY: check-structure test-api lint-api run-api test-console lint-console build-console run-console

check-structure:
	python3 scripts/check_structure.py

test-api:
	PYTHONPATH=backend $(PYTHON) -m pytest backend/tests

lint-api:
	$(PYTHON) -m ruff check --config backend/pyproject.toml backend scripts

run-api:
	PYTHONPATH=backend $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

test-console:
	npm --prefix frontend run test

lint-console:
	npm --prefix frontend run lint

build-console:
	npm --prefix frontend run build

run-console:
	npm --prefix frontend run dev
