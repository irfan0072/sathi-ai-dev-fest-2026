# Sathi task board

T+0: **confirmed — 1 October 2026, 10:00 AM Asia/Dhaka**. Delegation: **authorized by human on 2 October 2026**. Implementer: **`agy --print` read-only probe passed**.

The start gate is satisfied; this initial board covers Phase 0. Repository hygiene and empty component scaffolding are implemented; application hello-world and local containers are verified. Commands for planned tasks are proposed acceptance commands, not passed checks; completed-task results are recorded in the development log. Write each `tasks/T###.md` brief before delegation.

| ID | Title | Owner | Status | Dependencies | Acceptance criteria | Test command |
|---|---|---|---|---|---|---|
| T000 | Read source docs and inspect implementer | codex | Done (inspection only) | None | Read all 12 source files; document OS, CLI result and blockers | `uname -s`; `command -v antigravity`; `antigravity --help` (availability probe failed as documented) |
| T001 | Establish implementer workflow | codex | Done (probe passed) | Human provides CLI path/install or chooses alternative | Task input, cwd, file context, non-interactive mode and output verified from actual help | `agy --help`; `agy help agent`; read-only `agy --print` probe as recorded in workflow |
| T002 | Initialize local repository and ignore rules | antigravity | Done (Codex checks passed) |  T001, human go-ahead | Local Git initialized; `.env`, caches, dependencies and build artifacts ignored; `.env.example` has placeholders only; no remote operations | `git status --short`; `git check-ignore .env`; `git diff --check` |
| T003 | Set up empty component structure and dependency manifests | antigravity | Done (Codex checks passed) | T002 | Separate API, feature/model, verification, copilot and console boundaries following architecture; no business logic; record runtime/dependency versions | `make check-structure` |
| T004 | FastAPI hello-world and test runner | antigravity | Done (Codex checks passed) | T003 | Generic hello-world route, unit test and backend lint command; no mandate, data or policy implementation | `make test-api lint-api` |
| T005 | React hello-world and test runner | antigravity | Done (Codex checks passed) | T003 | Generic React hello-world, smoke test and lint/build commands; no product UI until T+0 confirmed | `make test-console lint-console build-console` |
| T006 | Docker Compose skeleton | antigravity | Done (approved retry; smoke passed) | T004, T005 | Postgres, API and console skeleton; placeholder env settings; no schema migration or synthetic seed | `docker compose config --quiet`; `make smoke-skeleton` |
| T007 | Aggregate local checks and CI | antigravity | Done (local and hosted CI passed) | T004, T005, T006 | `make test` and `make lint` run real component checks; CI matches local commands | `make test lint build-console`; `git diff --check` |
| T008 | Verify Phase 0 setup instructions | codex | Done (clean-clone checks passed) | T007 | README skeleton setup matches commands actually run; limitations and pre-existing artifacts disclosed; no claimed metrics | `make test lint build-console smoke-skeleton` |
| T009 | Confirm start and record time | codex | Done (human-confirmed) | Human T+0 confirmation | Exact official date, time and timezone recorded in decisions; later phases remain gated until confirmation | Manual comparison against human confirmation |
| T011 | Record approved validation setup | codex | Done (Codex checks passed) | Human approval | Approved seed/split agree across config and docs; fee/caps stay null | Exact config assertion in tasks/T011.md plus existing suite/linters |
| T010 | Publish skeleton and configure public remote | codex | Public remote done; runtime deployment deferred by human | T008, T009, explicit account/remote authorization | Full checks and smoke pass; approved public URL and Git remote verified; no secrets published | `make test lint build-console smoke-skeleton`; deployed smoke command to be specified in brief |

## Open design questions for later phases

- `region` is evaluation-only under the user rules and assumptions, but the configured agent model uses it in peer groups. Human resolution required before feature/model implementation.
- Requested mandates require non-null `code_hash` and `expires_at` in the schema, while code issuance follows verification. Clarify lifecycle storage without changing the schema yet.
- Verification is restricted to `customer_channel`, yet its response says `code_delivery: agent_terminal`; no authenticated agent delivery mechanism is defined.
- Wrong-code lockout and daily limits lack explicit persistence/contract details. Cash-gap tolerance, fee rate and caps are now approved; redemption lockout threshold remains unspecified.
- Validation seed 4242 and 60/20/20 agent split are human-approved; source config and evaluation plan updated. Fee/cap values are now approved in T012.

These are unresolved questions, not adopted design changes. Phase 0 is authorized and underway with Antigravity via agy; design questions gate dependent later work.

## Phase 1

| ID | Title | Owner | Status | Dependencies | Acceptance criteria | Test command |
|---|---|---|---|---|---|---|
| T012 | Record approved simulation assumptions | antigravity | Done (config assertions/full checks passed) | Human Phase 1 go-ahead | Approved defaults and auxiliary assumptions documented; uncovered decisions remain explicit | Config assertions; make test lint build-console |
| T013 | Schema migration and seed loader | antigravity | Done (28 backend tests/full checks passed) | T012 | Exact domain schema; transactional, repeatable migration/seed; no destructive reset | Database integration tests; make test lint build-console |
| T014 | Synthetic generator and leakage guard | antigravity | Done (full-scale determinism/seed checks passed) | T013 | Deterministic users/agents/transactions/sessions; configured noise/overlap and leakage enforcement before modeling | Generator determinism and leakage tests; full checks |
| T015 | Agent/seed split tooling & session correction | antigravity | Done (35 split tests/108,192 sessions verified) | T014 | Disjoint cohorts and seeds; credits get 0 sessions; seed dev DB verified | Disjointness tests; make test lint build-console; SQL counts |
| T015b | Distribution-shifted test artifact & deploy guide | antigravity | Done (test_shifted.json + render.yaml + deploy guide) | T015 | Separate shifted test artifact (obvious skimmers, 50% assisted, high noise); Render blueprint and deploy guide | make split; make test lint; test_shifted.meta.json |

## Phase 2 (Parallel Tracks — Models vs Mandate Service)

Target finish line: **4 October 2026 08:00 Asia/Dhaka** (Submission buffer). Report and video outline started by **3 October 2026 16:00 Asia/Dhaka**. Public skeleton deployment scheduled by **3 October 2026 14:00 Asia/Dhaka**.

Cut priority if behind:
1. Graph feature first
2. Voice speech recognition second (keep keypad)
3. LLM narrative third (keep deterministic templates)
Never cut: data generator, baselines, live demo path.

| ID | Title | Owner | Status | Dependencies | Acceptance criteria | Test command |
|---|---|---|---|---|---|---|
| T016 | Baseline rule implementations | antigravity | Done (7 unit tests passed) | T015 | Assisted rule (top_share >= 0.70 & hours <= 24) and agent rule (fee_ratio >= 1.2x); evaluation-only ground truth excluded | `pytest backend/tests/test_baselines.py` |
| T017 | Mandate service & deterministic policy | antigravity / agy | Done (18 unit/API tests passed) | T013, T015 | Scoped one-time mandates, SHA-256 hashed codes, TTL, single-use, lockout, audit log, config thresholds | `pytest backend/tests/test_mandates.py` |
| T018 | Assisted-user classifier (LightGBM) | antigravity | Done (6 ML tests/PR-AUC 0.866 passed) | T015, T016 | LightGBM model, calibration, SHAP values, PR-AUC sanity check (<=0.98), evaluation on validation split | `pytest backend/tests/test_assisted_model.py` |
| T019 | Agent anomaly detector | antigravity | Done (6 tests passed, 0 honest false-flags) | T015, T016 | Robust peer z-score + Isolation Forest, ranking, peer comparison reasons | `pytest backend/tests/test_agent_anomaly.py` |
| T020 | Evaluation suite & ablations | antigravity | Done (8 tests passed, docs/evaluation-results.md) | T016, T018, T019 | Baseline vs model tables, feature ablation, skimming sweep, noise sweep, distribution shift | `pytest backend/tests/test_evaluation.py` |
