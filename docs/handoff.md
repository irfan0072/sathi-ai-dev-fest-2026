# Sathi Handoff Document

This document records the exact state of the project, verified components, test commands, active ports, and next tasks. Update this document after every completed task so any orchestrator or engineer can resume seamlessly.

Last updated: 2026-10-02 18:18:00 Asia/Dhaka (12:18:00 UTC).
Lead engineer / Orchestrator: Antigravity (transitioned from Codex at 2026-10-02 18:01:37 Asia/Dhaka after Codex reached usage limit).

---

## 1. Project Timeline & Deadlines

- **Official T+0**: 1 October 2026, 10:00 AM Asia/Dhaka (confirmed by human).
- **Target Submission Finish Line**: 4 October 2026, 08:00 AM Asia/Dhaka (2-hour buffer before 10:00 AM deadline).
- **Report & Video Outline Gate**: 3 October 2026, 16:00 Asia/Dhaka.
- **Public Skeleton Deployment Gate**: Tonight / 3 October 2026, 14:00 Asia/Dhaka.
- **Current Time**: 2 October 2026, ~18:25 Asia/Dhaka.
- **Remaining to Target**: ~37.5 hours.

### Work Re-plan & Cuts if Behind Schedule
If falling behind schedule, feature cuts proceed in strict order:
1. **Graph feature first** (agent network / community graphs).
2. **Voice speech recognition second** (fall back strictly to keypad Bangla amount input; retain Bangla prompts).
3. **LLM narrative wording third** (fall back strictly to deterministic template-based receipts and case summaries).
*NEVER CUT*: Synthetic data generator, baseline comparisons (rules vs models), or the live demo path.

---

## 2. Current State & Verification Matrix

| Task | Title | Status | Verification Summary |
|---|---|---|---|
| T000 | Inspect environment & source documents | VERIFIED | All 12 source files read; macOS Darwin; PATH checked. |
| T001 | Implementer CLI workflow | VERIFIED | `agy` CLI found at `/Users/apple/.local/bin/agy`; non-interactive read-only probe passed. |
| T002 | Initialize repository hygiene | VERIFIED | Git initialized; `.gitignore` and `.env.example` in place; clean status. |
| T003 | Component structure & manifests | VERIFIED | `scripts/check_structure.py` passes; package manifests defined. |
| T004 | FastAPI health endpoint & test runner | VERIFIED | GET `/health` verified; pytest passes. |
| T005 | React console skeleton & test runner | VERIFIED | React 18 / Vite 8 / Vitest 4; test, lint, and build pass. |
| T006 | Docker Compose local skeleton | VERIFIED | PostgreSQL, API, and frontend containers running and healthy. |
| T007 | Aggregate checks & CI | VERIFIED | `make test lint build-console` passes locally; GitHub Actions CI passed. |
| T008 | Verify Phase 0 setup instructions | VERIFIED | Clean-clone verification documented in README.md. |
| T009 | Confirm start and record time | VERIFIED | T+0 recorded in `docs/decisions.md`. |
| T010 | Public remote configuration | VERIFIED | Remote `https://github.com/irfan0072/sathi-ai-dev-fest-2026.git` configured; runtime deployment deferred by human. |
| T011 | Record approved validation setup | VERIFIED | Seed 4242 and 60/20/20 agent split recorded and asserted in tests. |
| T012 | Record approved simulation assumptions | VERIFIED | All Phase 1 simulation defaults (fee 0.015, cap 5000, daily limit 25000, TTL 15m, cash gap tolerance, distributions, skimmer profiles) recorded and asserted. |
| T013 | Schema migration and seed loader | VERIFIED | 001_initial.sql migration, transaction rollback proofs, and seed loader tested against live PostgreSQL. |
| T014 | Synthetic generator & feature leakage guard | VERIFIED | Deterministic full-scale generation (seed 42: 20k users, 300 agents, 189,819 txns/sessions); leakage guard verified; zero ground-truth leakage into feature layer. |
| T015 | Agent/seed split tooling & dev DB seed | VERIFIED | Disjoint train (seed 42: 12k users, 180 agents), validation (seed 4242: 4k users, 60 agents), test (seed 2026: 4k users, 60 agents) cohorts generated and asserted. All 34 split tests pass, ruff passes. Dev DB seeded with exact SQL counts (20,000 users, 300 agents, 190,269 txns). |
| Mock | Console Mock Contract & Mock Server | VERIFIED | `docs/console-mock-contract.md` and `scripts/mock_server.py` created for parallel frontend development. |

---

## 3. Implementer CLI Status

- Path: `/Users/apple/.local/bin/agy`
- Mode tested: `--mode accept-edits --print "<task-prompt>"` with instructions restricting actions to file read/edit tools only.
- Test outcome: Verified on 2026-10-02 with a docstring edit on `scripts/smoke_skeleton.py`. Exited 0 headlessly without prompting for terminal permissions.
- Protocol: Antigravity CLI can be delegated file editing tasks directly from the command line.

---

## 4. Active Ports & Services

- **Localhost 18000**: Sathi API (`aidevfesthackathon-api-1` container -> internal port 8000).
- **Localhost 13000**: Sathi Console (`aidevfesthackathon-frontend-1` container -> internal port 80).
- **Localhost 5432**: Sathi PostgreSQL 16 (`aidevfesthackathon-db-1` container).
- **Localhost 8000**: Pre-existing system service (`php84` PID 92112). **DO NOT STOP OR INTERFERE**.
- **Localhost 5173 / 5174**: Vite development server (when running `make run-console`).

---

## 5. How to Run Tests & Verification

```sh
# 1. Structure, backend tests, and frontend tests
make test

# 2. Both linters (Ruff and ESLint)
make lint

# 3. Production frontend bundle build
make build-console

# 4. Full aggregate gate
make test lint build-console

# 5. Full backend tests including PostgreSQL integration tests
SATHI_TEST_DATABASE_URL="postgresql://sathi:CHANGE_ME@localhost:5432/sathi_phase1_test" \
  PYTHONPATH=backend .venv/bin/python -m pytest backend/tests

# 6. Container smoke check
make smoke-skeleton

# 7. Generate disjoint dataset splits
make split
```

---

## 6. Known Issues & Unresolved Design Questions

1. **Agent Peer Group vs Evaluation Slice (`region`)**:
   - `region` is defined as an evaluation-only slice under fairness rules, yet the agent anomaly model design in `docs/architecture.md` and `data/config.yaml` suggests peer groups based on `[region, volume_band]`.
   - Requires human confirmation before training agent anomaly models.
2. **Mandate Lifecycle Storage Columns**:
   - Schema defines non-null `code_hash` and `expires_at` at mandate row creation, while code generation logically follows verification. Clarify database persistence flow.
3. **Agent Terminal Delivery Mechanism**:
   - Verification is restricted to `customer_channel` role, but its response specifies `code_delivery: agent_terminal`. Need an authenticated agent retrieval endpoint or push mechanism.
4. **Lockout & Limit State Persistence**:
   - Wrong-code lockout threshold (distinct from verification attempt limit) and daily cash-out accumulation require explicit persistence tracking.

---

## 7. Next Actions

1. Commit verified T015 changes in small, clean steps once human approves.
2. Seed the main development database `sathi` with the disjoint splits (`train.json`, `validation.json`, `test.json`) and verify SQL counts (20,000 users, 300 agents).
3. Update `tasks/BOARD.md` marking T015 Done.
4. Transition to Phase 2:
   - T016: Baseline rule implementations (assisted-user rule baseline & agent fee-ratio rule baseline).
   - T017: Assisted-user classifier (LightGBM + calibration + SHAP).
   - T018: Agent anomaly detector (robust peer z-score + Isolation Forest).
   - T019: Deterministic mandate service & policy engine.
