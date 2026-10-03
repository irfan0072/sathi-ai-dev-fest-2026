# Final local verification — 3 October 2026

Verified code: `db41989bc3fbad871dbbbec9fcc7e0e125a9d5a5`; console commit `3e93c52`. Frozen model run: `ac18e14bd8f76e3ac4068e2037bfa7dbe29910a7`, bundle commit `69a48eb`. Later API/UI changes do not replace the frozen model provenance. All figures and identities are synthetic ASSUMPTIONS.

| Command/check | Actual result |
|---|---|
| `make test lint build-console SATHI_TEST_DATABASE_URL=postgresql://sathi:CHANGE_ME@127.0.0.1:5432/sathi_phase1_test` | Workspace:352backend/zero skips57.70s;30frontend;Ruff/ESLint/production build pass |
| Same command in independent clean checkout `/private/tmp/sathi-final-clean-20261003` |352backend/zero skips54.05s;30frontend;lint/build pass; locked dependencies installed from repository |
| `make init-env` and `docker compose config --quiet` in clean checkout | Generated ignored random signing secret without printing; Compose syntax passes |
| `make reproduce REPRODUCE_DIR=data/generated/final-source-verification` in clean checkout | Exit0, clean source `db41989`, dirty=false; every numerical JSON field equals frozen run after removing ONLY final_run_timestamp; split manifest/data hashes exactly equal |
| Curated committed bundle JSON validation | Hashes, schema, config/provenance and bounded snapshot pass; no untracked dataset required to load it |
| `docker compose build api` and `docker compose up -d api` | Bootstrap image built/running against preserved database; no deletion/reset |
| Repeated `prepare_runtime()` in running container | Preserved43910BDT and five cases at T026; no numpy/pandas/sklearn/lightgbm/shap/joblib imports |
| `make smoke-skeleton` | API200/ok with actual DBready/signingconfigured/artifactsverified; frontend200 |
| Independent bearer HTTP probe | Metrics exactly equal committed JSON;20saved outreach rows; anonymous401/customer403; runtime777 absent from model snapshot404; earlier receipt preserved |
| Actual browser dry run | Role switching;3000/45/3045;৩,০০০ confirmation; customer no terminal code; bound agent issue/redeem; duplicate issuance/replay rejected;2800cash report→200gap/tolerance60/case5; durable human escalation; separate2500 mismatch twice→cases6/7/second rejected |
| Receipt check after wording clarification |3focused tests/zero skips; Bangla ledger payable amount explicitly not proof of cash delivery |
| Local walkthrough |180s,1080×1920,H.264/embedded English captions; actual UI captures; HTML player displays captions; playback duration180/error=null/readyState4; receipt/SHAP/PR frames visually inspected |
| GitHub CI (authenticated read-only API) | Latest code `db41989` completed/success: [run37093569215](https://github.com/irfan0072/sathi-ai-dev-fest-2026/actions/runs/37093569215) |
| Repository visibility | Authenticated API says private=true; anonymous public access remains unavailable |

The final rehearsal also redeemed transaction424200038068, bringing the preserved synthetic balance to40865BDT; mismatch cases increased the case count to7. No seed/restart replenishes it. API18000,console13000,PG5432 remain local; PHP8000 is untouched. Test schemas are disposable only in the named local test database.

The Render blueprint parses and fields were reviewed against the official reference; it has not been applied or validated in a Render account. Local containers provide runtime proof, not a remote deployment claim. Public repository visibility, organizer-approved report/video formats, registration, accounts/devices and submission remain human facts.

Checks emitted existing upstream warnings: SHAP binary-classifier output notice and Starlette/httpx/status-name deprecations. No failed checks/skipped database tests in accepted final gates. Initial failed attempts and corrections remain in the complete [AI log](ai-dev-log.md); ignored raw logs contain no submission evidence claim.
