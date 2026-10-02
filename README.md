# Sathi (সাথী): Delegated Trust for Assisted MFS Users

AI DEV FEST 2026 (DIU CPC x upay), Track 07: Open Innovation. Team: Runtime Terrors.

**Current status: verified Phase 1 synthetic data generation and disjoint cohort splits; database seeding pending verification.** FastAPI health endpoint, React console, PostgreSQL container and migrations, deterministic synthetic generator, disjoint agent/seed splits (train/validation/test), seed loading implementation (database seeding pending verification), tests, linting, and production frontend build exist. Domain features below remain planned (no models or policy claimed). Official start confirmed by the human: 1 October 2026, 10:00 AM Asia/Dhaka. Public runtime deployment is deferred at the human's request; work remains local.

## 1. Project overview

Many users need help operating mobile wallets and may share their PIN with an agent or relative. Sathi proposes scoped, one-time, auditable cash-out mandates to reduce that exposure. It will check the customer's understanding of the amount in Bangla, identify users likely to need assistance, and flag abnormal agent activity for human review.

All data and reported outcomes will be synthetic/simulated. All financial, fee, and balance values are explicitly simulation ASSUMPTIONS, not actual upay figures. Amount verification checks comprehension; it does not detect coercion or lying. Models will never make allow/deny decisions: deterministic configuration rules and human review own those outcomes.

Repository: [irfan0072/sathi-ai-dev-fest-2026](https://github.com/irfan0072/sathi-ai-dev-fest-2026).

## 2. Features

| Feature | Status | Intended approach |
|---|---|---|
| Local API, console and database skeleton | Implemented and checked | FastAPI `/health`, React hello-world, PostgreSQL |
| Phase 1 synthetic generation & disjoint splits | Implemented (seeding pending verification) | Config-driven generator, deterministic RNG, disjoint agent cohorts (60/20/20), manifest tracking |
| Scoped one-time mandates | Planned | Deterministic policy, hashed codes, expiry and audit (no policy claimed) |
| Assisted-user detection | Planned | Rule baseline, LightGBM, SHAP and calibration (no models claimed) |
| Agent anomaly detection | Planned | Rule baseline, robust peer z-score and Isolation Forest (no models claimed) |
| Bangla amount verification | Planned | Keypad first, rule-based parser; optional speech interface |
| Receipts and case narratives | Planned | Optional LLM wording with numeric validation |
| Analyst console and review queue | Planned | Human decisions over structured evidence |

## 3. Technology stack

Verified on macOS with Python 3.13.2, Node 20.20.2 and npm 10.8.2. Current locked versions include FastAPI 0.142.2, React 18.3.1, Vite 8.3.2 and Vitest 4.1.11. Containers use Python 3.13, Node 20 for the frontend build, PostgreSQL 16 and Nginx. Docker Engine 29.6.2 and Compose 5.3.1 were used locally.

scikit-learn, LightGBM, SHAP and optional NetworkX are planned; they are not installed for this skeleton. No runtime LLM or speech service is connected.

## 4. Requirements

- Python 3.13 and a virtual environment for backend checks.
- Node `^20.19.0 || >=22.12.0`, npm, Git and Make for local development.
- Docker with Compose for the full local container stack.
- Free localhost ports 18000 (API), 13000 (console) and 5432 (database), or configure alternatives in your local `.env`.

No API keys, real customer data or external AI accounts are needed to run the skeleton. No hardware performance claim has been measured.

## 5. Installation and setup

These dependency-install and check commands were verified in an isolated clone of the public repository on 2 October 2026 (Phase 0 clean-clone verification):

```sh
git clone https://github.com/irfan0072/sathi-ai-dev-fest-2026.git
cd sathi-ai-dev-fest-2026
python3 -m venv .venv
.venv/bin/pip install -c backend/requirements-dev.lock -e 'backend[dev]'
npm --prefix frontend ci
make test lint build-console
```

The backend constraints file records tested runtime/dev versions; `frontend/package-lock.json` pins the frontend dependencies. Phase 0 clean-clone verification tested the initial test, lint, and build-console commands. Phase 1 schema migrations, synthetic dataset generation, disjoint train/validation/test split generation, and PostgreSQL seed loading are implemented (main database seeding pending verification by Codex). Model training commands remain planned.

## 6. Environment variables

`.env.example` contains placeholders only. Copy it to the ignored `.env` for local overrides:

```sh
cp .env.example .env
```

| Name | Purpose | Example/default |
|---|---|---|
| POSTGRES_USER / POSTGRES_DB | Local database identity | `sathi` |
| POSTGRES_PASSWORD | Required Compose database password | `CHANGE_ME` (local example only) |
| DATABASE_URL | Future backend database connection | `postgresql://sathi:CHANGE_ME@localhost:5432/sathi` |
| API_PORT / FRONTEND_PORT / POSTGRES_PORT | Localhost host ports | `18000` / `13000` / `5432` |
| API_URL / FRONTEND_URL | Smoke-check URLs | `http://127.0.0.1:18000/health` / `http://127.0.0.1:13000` |
| JWT_SECRET | Future token signing secret; currently unused | `CHANGE_ME` |
| SATHI_CONFIG | Configuration path | `data/config.yaml` |
| LLM_API_KEY / STT_API_KEY | Optional future services; currently unused | `YOUR_KEY_HERE` |

Compose constructs its internal database URL using the POSTGRES variables and the `db` hostname. The skeleton API does not connect to the database or authenticate users. Keep real secrets out of Git and replace placeholders before any future public deployment.

## 7. Run and build commands

Verified container startup:

```sh
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example up --build -d
make smoke-skeleton
docker compose --env-file .env.example ps
```

Open the console at [localhost:13000](http://127.0.0.1:13000) and API health at [localhost:18000/health](http://127.0.0.1:18000/health). The database retains data in a named development volume. Container host bindings are localhost only. Existing services on port 8000 are unaffected.

For your `.env` overrides, replace `--env-file .env.example` with `--env-file .env`. If URLs/ports differ, invoke the smoke checker explicitly:

```sh
python3 scripts/smoke_skeleton.py --api-url http://127.0.0.1:18000/health --frontend-url http://127.0.0.1:13000
```

The API image contains a snapshot of `data/config.yaml`; rebuild with `up --build -d` after config edits. No host bind mount or Docker file-sharing change is required.

Local development commands in separate terminals:

```sh
make run-api       # localhost:18000; override with API_PORT=...
make run-console   # Vite prefers localhost:5173; chooses the next free port if occupied
```

`make build-console` produces the ignored `frontend/dist` bundle. The Vite development port differs from the container console port; use the URL printed by Vite. The development commands were verified from the clean clone using API port 18001 and Vite port 5174 to avoid existing listeners. Stop this development stack without removing its database volume with `docker compose --env-file .env.example stop`.

### Synthetic data generation, splits, and database seeding

Make does not automatically source `.env`; export `DATABASE_URL` explicitly in your host terminal before running database commands:

```sh
# Explicitly export the host DATABASE_URL for local Make commands (Make does not source .env)
export DATABASE_URL="postgresql://sathi:CHANGE_ME@localhost:5432/sathi"

# Optional: override target database schema (search_path)
# export DATABASE_SCHEMA="public"

# Dedicated test database URL for running integration database tests:
# export SATHI_TEST_DATABASE_URL="postgresql://sathi:CHANGE_ME@localhost:5432/sathi_test"

# Apply schema migrations to PostgreSQL
make migrate

# Generate single-file dataset as a separate inspection artifact (seed 42)
make generate

# Generate disjoint train, validation, and test splits with canonical manifest
make split

# Seed individual disjoint splits into PostgreSQL (pending verification)
make seed DATASET=data/generated/splits/train.json
make seed DATASET=data/generated/splits/validation.json
make seed DATASET=data/generated/splits/test.json
```

- **Main dev DB `sathi` (pending verification)**: Main database seeding is implemented, with end-to-end database verification pending Codex execution in the next gate. Once verified, seeding train, then validation, then test executes without ID collision, loading the full combined 20,000 customers/users and 300 agents, and repeating any or all seed steps is an idempotent no-op.
- **Standalone generation artifact**: `make generate` produces `data/generated/train.json` (and sidecar `train.observations.json`) as a separate inspection artifact using seed 42. Because the disjoint train split (`data/generated/splits/train.json`) also uses seed 42, do not seed both the standalone artifact and the disjoint train cohort into the same database schema, as their user IDs (`U_42_*`) overlap.
- **Disjointness and isolation**: Train, validation, and test cohorts are mutually disjoint across agents (180/60/60) and customers (12,000/4,000/4,000). Every transaction and session routes strictly within its cohort.
- **Git ignore**: All generated files in `data/generated/` are ignored by Git.
- **Immutable seed provenance**: Changing simulation configuration requires a fresh dev dataset database/schema or new seed namespaces; no reseed overwrite or reset command exists to prevent test/train contamination.
- **Evaluation boundary**: Generating the test split artifact is strictly for isolation and reproducible storage; no test set training and no scored metric evaluation are performed. No models or policy rules are claimed.

## 8. Live deployment URL

Pending. The human requested local work for now. There are no demo logins or public runtime URL; the public GitHub repository contains the source and continuous commit history.

## 9. Testing instructions

```sh
make test lint build-console
docker compose --env-file .env.example config --quiet
make smoke-skeleton  # requires the running local containers
```

`make test` checks component structure and runs one backend health test and one React render test. `make lint` runs Ruff and ESLint. GitHub Actions runs the same tests, lint, frontend build and Compose config validation. The HTTP smoke check verifies API JSON and the console HTML; a browser check also confirmed the rendered hello-world page locally.

The existing TestClient emits a nonfatal HTTPX deprecation warning. npm reports zero known vulnerabilities for the current lockfile; ESLint 9 emits a support/deprecation notice. Domain, security, model and fairness tests will be added with their features. There are no evaluation metrics or metric reproduction commands yet. The future domain demo in `docs/demo-script.md` cannot be run against this skeleton.

## 10. Other configuration

Thresholds and synthetic assumptions live in `data/config.yaml` and `data/assumptions.md`. Simulation seeds are 42 (train), 4242 (validation), and 2026 (test). The 300 agents are partitioned into disjoint cohorts using a 60/20/20 split (180 train, 60 validation, 60 test) stratified across normal (162/54/54), high-volume honest (12/4/4), and skimmer (6/2/2) types. Customers are partitioned 12,000 train, 4,000 validation, and 4,000 test.

All financial values, fee rates, balances, and caps are explicitly simulation ASSUMPTIONS, not actual upay figures or commercial tariffs: approved simulation assumptions include official fee rate (0.015 / 1.5%), user mandate cap (5,000 BDT default), daily cash-out limit (25,000 BDT), mandate TTL (15 min), max verification attempts (2), and cash gap tolerance `max(50, 0.02 * amount)`. Documented auxiliary generator defaults include initial balance (5,000 BDT), minimum cash-out (100 BDT), 50 BDT rounding increment, and independent loyal fraction (0.15). Region is evaluation-only under the project rules, while a proposed peer-group setting includes it; that conflict awaits human resolution before model implementation. Mandate lifecycle/storage and code-delivery contract questions also remain open in `tasks/BOARD.md` and `docs/decisions.md`.

## Disclosures

Planning documents and the proposed schema/config were supplied before implementation; see `docs/ai-dev-log.md` for the recorded development history and `docs/decisions.md` for human approvals. Codex orchestrates and independently reviews/tests Antigravity CLI (`agy`) output. No external datasets, customer data, paid runtime APIs or model weights are used. Open-source dependency manifests, lockfiles and container definitions are included. Submission artifacts and measured results remain future work.
