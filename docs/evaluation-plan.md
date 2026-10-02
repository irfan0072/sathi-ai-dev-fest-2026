# Evaluation Plan

## 1. What we measure and why
| Goal | Metric | Baseline | Target (set after first run) |
|---|---|---|---|
| Find users who need help | PR-AUC; recall at fixed precision; calibration | Rule: top-agent share >= 70% and cash-out within 24h of credit | [ ] |
| Find abnormal agents | precision@k, recall on injected skimmers; false-flag rate on honest high-volume agents | Rule: fee ratio above 1.2x official | [ ] |
| Stop PIN disclosure | % assisted cash-outs completed without PIN disclosure (simulated) | 0% protected | [ ] at 30/50/70% adoption |
| Reduce loss | Simulated skimming loss prevented | No Sathi | [ ] |
| Keep friction low | Review rate; verification completion rate; time to complete | n/a | [ ] |

## 2. Splits and leakage rules
- Split by agent and seed, not by row. Test agents are never seen in training.
- Tune thresholds on validation only; touch the test set once per reported run.
- Exclude generator ground-truth columns (group_label, agent_type) from features.

## 3. Experiments
1. Baseline vs LightGBM on assisted-user detection, with and without label noise.
2. Peer z-score vs Isolation Forest vs combined for agents.
3. Skimming intensity sweep: subtle, moderate, obvious.
4. Ablation: remove session signals; remove cash-received confirmation; show contribution of each.
5. Adoption sensitivity: 30%, 50%, 70%.
6. Robustness: change simulation parameters in the test seed (distribution shift) and re-evaluate.

## 4. Fairness
Slice by gender, age band, region, urban/rural (evaluation only). Report TPR, FPR and review rate per slice, and the maximum TPR gap against the config target. If a gap exceeds the target, state it and the mitigation.

## 5. Explainability
SHAP for the assisted-user model; peer comparison table for agents; every review case shows its top reasons.

## 6. Verification flow quality
Keypad and voice: completion rate, mismatch rate, number-parsing accuracy on a test set of spoken amounts (varied speakers if possible), fallback rate.

## 7. Copilot safety checks
- Numbers in generated text must match database values (automatic check).
- Prompt-injection tests via free-text fields (agent note, customer name).
- Refusal to make decisions; outputs labelled as generated explanations.

## 8. Reporting rules
State clearly: synthetic data, simulated impact, assumptions in assumptions.md. Show confidence intervals or multiple seeds where possible.
