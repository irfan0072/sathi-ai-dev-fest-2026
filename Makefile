PYTHON ?= .venv/bin/python
API_PORT ?= 18000
DATASET ?= data/generated/train.json
SATHI_TEST_DATABASE_URL ?= postgresql://sathi:CHANGE_ME@localhost:5432/sathi_phase1_test
CONFIG ?= data/config.yaml
SPLITS_DIR ?= data/generated/splits
EVAL_DIR ?= data/generated/evaluation

.PHONY: test lint check-structure test-api lint-api run-api test-console lint-console build-console run-console smoke-skeleton migrate seed generate split init-env demo-seed reproduce live-preflight live-tests live-tests-bd-ivr-standin live-standin-up live-standin-down scale-seed smoke-roles

test: check-structure test-api test-console

lint: lint-api lint-console

check-structure:
	python3 scripts/check_structure.py

test-api:
	SATHI_TEST_DATABASE_URL=$(SATHI_TEST_DATABASE_URL) PYTHONPATH=backend $(PYTHON) -m pytest backend/tests

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

split:
	PYTHONPATH=backend $(PYTHON) -m app.data.cli split

init-env:
	python3 scripts/init_env.py

demo-seed:
	PYTHONPATH=backend $(PYTHON) -m app.data.cli demo-seed

REPRODUCE_DIR ?= data/generated/reproduce_run
REPRODUCE_SPLITS_DIR ?= $(if $(filter data/generated/splits,$(SPLITS_DIR)),$(REPRODUCE_DIR)/splits,$(SPLITS_DIR))
REPRODUCE_EVAL_DIR ?= $(if $(filter data/generated/evaluation,$(EVAL_DIR)),$(REPRODUCE_DIR)/evaluation,$(EVAL_DIR))

reproduce:
	PYTHONPATH=backend $(PYTHON) -m app.data.cli split --config $(CONFIG) --output-dir $(REPRODUCE_SPLITS_DIR)
	PYTHONPATH=backend $(PYTHON) scripts/evaluate.py --config $(CONFIG) --splits-dir $(REPRODUCE_SPLITS_DIR) --output-dir $(REPRODUCE_EVAL_DIR)

# ---------------------------------------------------------------------------
# Live 3rd-party integration: preflight + guarded live tests
# ---------------------------------------------------------------------------
# Run scripts/preflight.py against the .env in the current directory. Probes
# each configured provider with auth-only requests; never places a call or
# sends SMS. Exit code 1 if any probe fails.
live-preflight:
	python3 scripts/preflight.py

# Run backend/tests/test_live_providers.py with SATHI_LIVE_TESTS=1. Every
# live test skips individually when its provider env vars are missing.
# Requires real Twilio / Alpha SMS / Gemini / OpenAI keys in .env.
live-tests:
	SATHI_LIVE_TESTS=1 SATHI_TEST_DATABASE_URL=$(SATHI_TEST_DATABASE_URL) PYTHONPATH=backend $(PYTHON) -m pytest backend/tests/test_live_providers.py -v

# Bring up the local BD-IVR stand-in (compose `live` profile). Only useful
# until a real Bangladesh IVR vendor confirms the JSON contract.
live-standin-up:
	docker compose --profile live up -d bd_ivr_standin

live-standin-down:
	docker compose --profile live down

# Roundtrip the BD-IVR webhook contract end-to-end against the stand-in.
# Assumes .env has SATHI_BD_IVR_API_KEY + SATHI_BD_IVR_WEBHOOK_SECRET set.
live-tests-bd-ivr-standin:
	SATHI_LIVE_TESTS=1 PYTHONPATH=backend $(PYTHON) -m pytest backend/tests/test_live_providers.py -v -k bd_ivr

# Load a platform-scale synthetic population (default 5,000,000 customers) into DATABASE_URL.
SCALE_USERS ?= 5000000
scale-seed:
	$(PYTHON) scripts/scale_seed.py --users $(SCALE_USERS)

# Role-split smoke test against the running API.
smoke-roles:
	bash scripts/smoke_roles.sh
