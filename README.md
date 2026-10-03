# Sathi (সাথী): Delegated Trust for Assisted MFS Users

AI DEV FEST2026, DIU CPC × upay, Track07 Open Innovation. Team: Runtime Terrors.

**Verified local synthetic prototype.** Full352backend tests/zero skips,30frontend tests, lint and production build pass. Browser roles, Bangla confirmation, terminal-only one-time codes, redemption/replay rejection, cash-gap review and ledger receipts work against the real API. Automatic startup preserves spent balances. Held-out assisted PR-AUC0.8091 versus rule0.6967; agent ensemble detects2/2 injected skimmers with0/4 honest high-volume false flags (small denominators). Public hosting remains pending; the human requested local work. See [verification record](docs/verification-record.md).

## Overview and features

Sathi explores scoped, expiring, one-time cash-out authority instead of sharing a reusable customer PIN. The customer confirms an amount through a keypad; the bound agent terminal receives a code after verification. Deterministic configuration and ledger checks govern redemption. Behavioral models support outreach and human review, and never authorize or deny a transaction.

| Feature | Verified status |
|---|---|
| Synthetic users/agents/transactions/sessions; deterministic disjoint agent/seed splits | Implemented and tested; original development dataset preserved |
| Assisted rule/LightGBM with disjoint calibration and faithful SHAP | T023b verified results and saved models |
| Agent fee rule, train-derived volume peers and Isolation Forest | T023b verified rules/model/report-signal comparisons |
| Scoped synthetic JWT, durable mandates/attempts/locks/ledger/audit | T024 local API verified |
| Keypad/Bangla digits, terminal-only code, cash reports, real receipts/cases | Actual API/browser flow verifiedT025 |
| React console | Scoped in-memory role login; verified saved outreach/risk/metrics; unavailable evidence fails closed |
| Local walkthrough/report package | [Recorded walkthrough](docs/demo-walkthrough.html), [MP4](docs/demo-walkthrough.mp4), [report](docs/report-draft.md) |
| Public deployment | Pending human dashboard action; no live URL claimed |

Financial figures are **ASSUMPTIONS**, never actual upay rates. All identities/data/transactions are synthetic. Amount confirmation cannot establish coercion, honesty, speaker identity or physical cash delivery. No real upay integration, voice recognition or external LLM is implemented in the verified flow.

## Stack and requirements

Python3.13.2, FastAPI, PostgreSQL16, React18.3.1/Vite8.3.2, scikit-learn1.9.1, LightGBM4.7.0, SHAP0.52.0 and PyJWT2.15.1. Tested runtime/dev versions are pinned in `backend/requirements-dev.lock`; frontend dependencies in `frontend/package-lock.json`. Linux native model imports were checked in the API image, which includes `libgomp1`.

Use Python3.13, Node20.19+ or22.12+, npm, Git, Make, Docker and Compose. Local host ports are API18000, console13000 and Postgres5432. Existing PHP8000 is independent. No external AI key or real customer credential is required.

## Install and run locally

```sh
git clone https://github.com/irfan0072/sathi-ai-dev-fest-2026.git
cd sathi-ai-dev-fest-2026
python3 -m venv .venv
.venv/bin/pip install -c backend/requirements-dev.lock -e 'backend[dev]'
npm --prefix frontend ci
make init-env
docker compose up --build -d
make smoke-skeleton
```

The repository currently requires authenticated Git access; make it public before submission. Final committed source was checked independently from a clean checkout with locked dependencies. Compose startup validates signing/config/artifacts before writes, applies existing migrations and seeds only the small namespace777 demo. It never generates training data or replenishes spent balances. The local production-shaped bootstrap and repeated restart are verified; Render itself has not been deployed.

`make init-env` creates ignored `.env` and generates a random signing secret without printing it; valid existing values are preserved. Runtime Compose reads `.env`. Do not override it with `--env-file .env.example`: the example signing placeholder fails authentication. Database data persist in the named volume; `docker compose stop` preserves them. Do not remove volumes to troubleshoot.

Open [local console](http://127.0.0.1:13000) and [API health](http://127.0.0.1:18000/health). Sign in using the public synthetic fixture roles below. Rebuild the API after code/config edits. For host development, `make run-api` and `make run-console` require explicitly supplied environment variables; Make does not source `.env`. Vite prints its development port, which can differ from the container's13000.

## Environment names

| Name | Purpose |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local Compose database; example password is for local testing only |
| `DATABASE_URL` | API database connection; Compose constructs its internal DSN |
| `JWT_SECRET` | Required server signing secret, generated locally or by Render; never commit/share |
| `SATHI_CONFIG` | Configuration path, default `data/config.yaml` |
| `SATHI_ARTIFACTS_DIR` | Trusted local curated bundle, default `data/artifacts/deployment`; verified before use, no runtime model loading |
| `PORT` | Bootstrap container/hosting port, default8000; Compose maps to host18000 |
| `API_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT` | Host bindings, defaults18000/13000/5432 |
| `API_URL`, `FRONTEND_URL` | Smoke-test URLs |
| `CORS_ORIGINS` | Explicit allowed console origins; production needs the actual public HTTPS origin |
| `VITE_API_URL` | Build-time browser API URL; production requires actual public HTTPS API |
| `SATHI_TEST_DATABASE_URL` | Dedicated local test database, never production |
| `LLM_API_KEY`, `STT_API_KEY` | Unused optional placeholders; no runtime dependency |

## Synthetic demo principals

| Principal | Public fixture PIN | Scope |
|---|---|---|
| `demo_agent` | `1234` | `A_777_000001`, permitted customer `U_777_000001` only |
| `demo_customer` | `5678` | Own amount verification/cash report/receipt; no terminal code |
| `demo_analyst` | `9012` | Human-review cases and saved synthetic evidence; no redemption |

Use the console’s role selector or `POST /api/v1/auth/demo-login` using the API contract. JWTs remain in browser memory; switching roles/signing out clears them. These public fixture PINs are synthetic demo data, separate from the private signing secret. The initial assumed50,000BDT credit is never replenished by repeated seeding. A3,000BDT mandate has assumed45BDT fee and3,045BDT debit. See [API contracts](docs/api-contracts.md) and [demo script](docs/demo-script.md).

## Tests and build

Create a dedicated local test database once while Postgres is running:

```sh
docker compose exec -T db createdb -U sathi sathi_phase1_test
make test lint build-console
make smoke-skeleton
```

If the test database already exists, retain it. Tests use isolated disposable schemas in that dedicated database. The Makefile's local example DSN uses the example local password; if your local password/port differs, set `SATHI_TEST_DATABASE_URL` accordingly without committing it. Backend checks cover determinism, leakage, disjointness, models, authentication, parsing, persistence/concurrency, replay/lockout and receipts; frontend checks cover the current console. GitHub CI for code db41989 is independently verified completed/success in the [verification record](docs/verification-record.md); later commits need their own CI confirmation.

## Simulation and reproducibility

Config/assumptions live in [config](data/config.yaml) and [assumptions](data/assumptions.md). Seeds42/4242/2026 and agent split60/20/20 produce180/60/60 agents and12,000/4,000/4,000 users. Demographics, group labels and agent types are evaluation-only, including peer selection. The shifted test is separate from canonical test. Ordinary tests use tiny generated fixtures and never score final canonical cohorts.

Approved placeholders:1.5% fee,5,000BDT mandate cap,25,000BDT Dhaka-calendar daily limit,15-minute TTL, verification2 attempts, wrong-code3 attempts and cash-gap tolerance `max(50BDT,2% of amount)`. Generation preserves overlap/noise; no tuning to a score.

Run the full frozen-config evaluation in a new directory:

```sh
make reproduce REPRODUCE_DIR=data/generated/my-reproduction
```

This generates disjoint train/validation/test and separate shifted data, checks provenance, fits train-only models with disjoint validation calibration, enforces the validation sanity ceiling, and saves results/Markdown/models/manifests plus a bounded deployment bundle. Default training sample is4,000users; complete test cohorts are scored. The final verified run is `data/generated/final-20261003`; raw data remain ignored. Reviewed small artifacts are committed in `data/artifacts/deployment`, with full source/data/dependency provenance in `data/artifacts/evaluation-manifest.json`. Numerical results are [here](docs/evaluation-results.md), including baselines, shifted results, ablations, fairness denominators and idealized adoption30/50/70. Use a fresh directory; retain older datasets. The namespace777 runtime ledger is separate from the offline30-day simulation snapshot at2026-12-30. Synthetic results do not establish real accuracy or fraud reduction.

## Deployment and disclosures

Public runtime URL: pending. Work remains local until the verified guide and human dashboard deployment. See [Render preparation](docs/deploy-guide.md); never use guessed service URLs or send credentials. Package and remaining human compliance facts are recorded in [report draft](docs/report-draft.md), [task board](tasks/BOARD.md) and [rules checklist](docs/rules-checklist.md).

Codex orchestrated, edited docs/config, independently reviewed/tested and managed Git. With explicit human approval it also implemented repairs and the final console/bootstrap when Antigravity quota was exhausted or CLI transport stalled. Antigravity IDE produced inherited work and remains paused; Antigravity CLI(agy1.2.15) completed earlier implementation tasks. See [complete development history](docs/ai-dev-log.md) and [decisions](docs/decisions.md). Source planning/schema/config preceded implementation as disclosed. No real PII, upay data, external dataset, paid runtime API or pretrained external model weights are used. Dependencies are open source; GitHub hosts source and Render is planned hosting. A bounded qualitative study informs the problem framing and is cited in the report; it does not validate simulation accuracy or national prevalence.
