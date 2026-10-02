# T022 — human-approved narrow retry
Human: 'Resume with the narrow test and lint corrections'. Code edits only; no commands/install/Git/docs/config/task edits.
1. backend/tests/test_evaluation.py:test_experiment_4_signal_ablations incorrectly checks res[key]['roc_auc'], which actual ablation schema does not provide. Remove that invalid assertion; retain PR-AUC range and assert delta_pr_auc equals variant PR-AUC minus full-model PR-AUC within rounding tolerance. No metric fabrication/API changes.
2. Wrap exactly six Ruff E501 lines: backend/app/analytics/service.py353; backend/app/copilot/receipts.py58; backend/tests/test_analytics.py139; backend/tests/test_evaluation.py182,206,348. No broad changes.
Codex will rerun full suite/lint/build and local container smoke after review. Report changed files briefly.
Additional discovered lint error from the same pre-retry code: frontend/src/components/LiveSimulation.jsx143 catch(_err) defines unused variable under ESLint. Change to catch without binding if unused. This is within the approved narrow lint correction scope. No other behavior change.
