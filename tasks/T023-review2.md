# T023 second failed gate — requires human go-ahead
No implementation until human approval. Same approved design, no new architecture/API. After approval agy code-only, no commands/install/Git/docs/config/tasks edits.

Verified second pass: structure passes; backend208pass/5fail,zero skips; Ruff3findings; diffcheck clean. Prior frontend17tests/lint/build passed; unchanged this pass, make stopped before frontend. Exact backend failure reasons:
1. test_agent_detector_invalid_overrides calls nonexistent review_top_k constructor argument. Test invalid config via validated config dict; preserve public constructor unless already intended override supplied. Do not invent API to satisfy a test.
2. test_agent_detector_explain_batch_rejection omits agent_id; pass synthetic agent ID and two-row DataFrame to existing explain(agent_id,X_row) and assert actual batch rejection.
3-5. Same-object and single-class calibration tests, and protected-peer config test, expect stale exact exception messages. Keep behavior checks, align stable matching to actual error type/meaning; do not weaken rejection or add success-score floors.
Ruff exact tasks/T023-second-lint-output.txt: agent_model.py:368 long comment, test_baselines.py/test_evaluation.py extra blank separating first-party imports from third-party contrary project Ruff config. Wrap/remove exact blanks, no globalformat changes.

Critical reproduced fitted-state bug: fit(validtrain,validval), then fit(sameX, inverted_y) without validation raises ValueError AFTER replacing base estimator. Probe shows Base preserved=False, Old calibration retained=True, Raw predictions preserved=False. This breaks explanation/calibration fidelity after a rejected fit.
- Validate train AND validation matrices/1D binary targets/two classes/exact proposed schema and separate object identity BEFORE changing fitted state or fitting. Construct new base/calibrator/schema in locals; assign self fields only after both training/calibration succeed. Failed refit must raise and preserve existing fitted model/calibration/schema/explainer, or explicitly invalidate all consistently; prefer atomic preserved state.
- Add regression: valid fit, rejected missing/NaN/oneclass/2D calibration refit, base margins/calibrated probabilities/raw-SHAP additivity/save-load unchanged. Fresh invalid fit stays unfitted and unsaveable. Never silently suppress fit errors.
- Review final small fixture sanity test: no forced score floor/ceiling/pass; only finite[0,1] and sanity boolean equals actual configured comparison. Calibration separation test compare same-seed train-only estimator base margins and inverted validation labels, not shapes alone. Keep stratified generated fixtures and no canonical final scoring.

Codex verifies focused+full tests/lint/build and fitted-state regression, then commit/push/handoff. No durable T024 or final artifact task until this gate resolved. Preserve uncommitted changes.
