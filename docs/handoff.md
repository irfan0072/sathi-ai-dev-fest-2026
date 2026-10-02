# Sathi Handoff Document

This document records the exact state of the project, verified components, test commands, active ports, and next tasks. Update this document after every completed task so any orchestrator or engineer can resume seamlessly.

Last updated: 2026-10-02 18:52:00 Asia/Dhaka (12:52:00 UTC).
Lead engineer / Orchestrator: Antigravity (transitioned from Codex at 2026-10-02 18:01:37 Asia/Dhaka after Codex reached usage limit).

---

## 1. Project Timeline & Deadlines

- **Official T+0**: 1 October 2026, 10:00 AM Asia/Dhaka (confirmed by human).
- **Target Submission Finish Line**: 4 October 2026, 08:00 AM Asia/Dhaka (2-hour buffer before 10:00 AM deadline).
- **Report & Video Outline Gate**: 3 October 2026, 16:00 Asia/Dhaka.
- **Public Skeleton Deployment Gate**: Tonight / 3 October 2026, 14:00 Asia/Dhaka.
- **Current Time**: 2 October 2026, ~18:52 Asia/Dhaka.
- **Remaining to Target**: ~37.1 hours.

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
| T004 | FastAPI health endpoint & test runner | VERIFIED | GET `/health` verified; pytest passes. CORS middleware configured from env. |
| T005 | React console skeleton & test runner | VERIFIED | React 18 / Vite 8 / Vitest 4; test, lint, and build pass. |
| T006 | Docker Compose local skeleton | VERIFIED | PostgreSQL, API, and frontend containers running and healthy. |
| T007 | Aggregate checks & CI | VERIFIED | `make test lint build-console` passes locally; GitHub Actions CI run #37006945421 verified GREEN. |
| T008 | Verify Phase 0 setup instructions | VERIFIED | Clean-clone verification documented in README.md. |
| T009 | Confirm start and record time | VERIFIED | T+0 recorded in `docs/decisions.md`. |
| T010 | Public remote configuration | VERIFIED | Remote configured; Render blueprint `render.yaml` and `docs/deploy-guide.md` prepared. |
| T011 | Record approved validation setup | VERIFIED | Seed 4242 and 60/20/20 agent split recorded and asserted in tests. |
| T012 | Record approved simulation assumptions | VERIFIED | All Phase 1 simulation defaults recorded and asserted. |
| T013 | Schema migration and seed loader | VERIFIED | 001_initial.sql migration, transaction rollback proofs, and seed loader tested against live PostgreSQL. |
| T014 | Synthetic generator & feature leakage guard | VERIFIED | Deterministic full-scale generation; leakage guard verified; zero ground-truth leakage into feature layer. |
| T015 | Disjoint split tooling & session correction | VERIFIED | Generator fixed: credit deposits get 0 sessions; sessions (108,192) reflect only user-initiated txns (`cash_out`, `send`, `bill_pay`). Total txns 190,256. Reseeded dev DB verified. |
| T015b | Distribution-shifted test artifact | VERIFIED | `generate_shifted_test_split` creates `test_shifted.json` (39,962 txns, 22,210 sessions) with obvious skimmers, 50% assisted share, and degraded recall accuracy. `test.json` untouched. |
| T016 | Baseline rule implementations | VERIFIED | `AssistedUserRuleBaseline` and `AgentAnomalyRuleBaseline` implemented with strict leakage guard; 7 unit tests passing. |
| T017 | Mandate service & policy engine | VERIFIED | Scoped mandates, SHA-256 hashed codes, TTL expiry, 3-attempt lockout (423), cash gap anomaly detection, audit log, and FastAPI router mounted in `app.main`; 18 unit/API tests passing. |
| T018 | Assisted-user classifier (LightGBM) | VERIFIED | LightGBM classifier with CalibratedClassifierCV, SHAP TreeExplainer local reasons, fairness slice breakdown, and PR-AUC sanity check (<= 0.98; observed 0.866 on validation split); 6 ML tests passing. |
| Mock | Console Mock Contract & Mock Server | VERIFIED | `docs/console-mock-contract.md` and `scripts/mock_server.py` default port set to 18001 (isolated from live API on 18000). |
| Deploy | Render Deployment Config & Guide | VERIFIED | Declarative `render.yaml`, `backend/requirements.txt`, and `docs/deploy-guide.md` created with sleep limits, env var names, health checks, and low-privilege demo logins. |

---

## 3. Test Suite Status

- **Total Backend Tests**: 162 tests passed, 0 skipped, 0 failed.
- **Frontend Tests**: 1 vitest test passed.
- **Linters**: Both Ruff (backend/scripts) and ESLint (frontend) pass with 0 errors.

---

## 4. Active Ports & Services

- **Localhost 18000**: Sathi API (`aidevfesthackathon-api-1` container -> internal port 8000).
- **Localhost 18001**: Sathi Mock API Server (`scripts/mock_server.py` for frontend development).
- **Localhost 13000**: Sathi Console (`aidevfesthackathon-frontend-1` container -> internal port 80).
- **Localhost 5432**: Sathi PostgreSQL 16 (`aidevfesthackathon-db-1` container).
- **Localhost 8000**: Pre-existing system service (`php84` PID 92112). **DO NOT STOP OR INTERFERE**.
- **Localhost 5173 / 5174**: Vite development server (when running `make run-console`).

---

## 5. Next Tasks in Priority Order

1. **T019: Agent Anomaly Detector**:
   - Robust peer z-score + Isolation Forest across peer groups (`region`, `volume_band`).
   - Ranking and peer comparison reason generation.
   - Unit tests in `backend/tests/test_agent_anomaly.py`.
2. **T020: Comprehensive Evaluation Suite & Ablations**:
   - Baseline vs Model comparison tables (Precision, Recall, F1, PR-AUC).
   - Skimming intensity sweep (subtle, moderate, obvious).
   - Feature ablations (session signals removed, cash confirmation removed).
   - Robustness evaluation on distribution-shifted test split (`test_shifted.json`).
3. **Public Deployment**:
   - Ready for dashboard deployment via `render.yaml` and `docs/deploy-guide.md`.


