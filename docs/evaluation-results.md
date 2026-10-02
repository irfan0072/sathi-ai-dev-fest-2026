# Sathi Evaluation & Experimentation Results

> PROVISIONAL inherited run: do not use these numbers as final submission or console evidence. The resume audit found fit/calibration, cohort scaling and ablation defects. Retained for provenance until corrected artifacts replace it. See docs/audit-2026-10-02.md.

> [!NOTE]
> All evaluations use synthetic MFS simulation data generated with disjoint cohorts per `docs/evaluation-plan.md` (Train Seed 42, Validation Seed 4242, Test Seed 2026). Zero protected demographic features or ground truth labels were included in model feature matrices.

## 1. Assisted-User Classifier vs Rule Baseline

| Model | PR-AUC | ROC-AUC | Brier Calibration Score | Recall @ 80% Precision |
|---|---|---|---|---|
| Rule Baseline (top_share >= 0.70 & hours <= 24) | 0.7737 | 0.7681 | 0.1890 | 0.0000 |
| **Sathi LightGBM Classifier (Clean)** | **0.8028** | **0.8970** | **0.0929** | **0.8950** |
| Sathi LightGBM (5% Label Noise) | 0.8036 | 0.8966 | 0.0956 | 0.8957 |

## 2. Agent Anomaly Detection: Ensemble & Baseline Comparison

| Model / Method | Precision@R (Top-K) | Recall on Injected Skimmers | False-Flag Rate on Honest High-Volume |
|---|---|---|---|
| Baseline Rule (fee ratio >= 1.2x official) | 1.00 | 0.00 | 0.00 |
| Peer Robust Z-Score (Median & MAD) | 1.00 | 1.00 | 0.00 |
| Isolation Forest (Unsupervised) | 1.00 | 1.00 | 0.00 |
| **Sathi Combined Ensemble (0.70 Z + 0.30 IF)** | **1.00** | **1.00** | **0.00** |

## 3. Skimming Intensity Sweep

| Tier | Intensity Description | Fee Overcharge | Mean Risk Score | High-Risk Flag Rate |
|---|---|---|---|---|
| Subtle | 5% fee overcharge, 5% cash reduction | 1.05x | 0.518 | 0.0% |
| Moderate | 15% fee overcharge, 15% cash reduction | 1.15x | 0.785 | 28.3% |
| Obvious | 35% fee overcharge, 30% cash reduction | 1.35x | 0.785 | 28.3% |

## 4. Behavioral Feature Signal Ablations

| Feature Configuration | Description | PR-AUC | Delta vs Full |
|---|---|---|---|
| full_model | 0 dropped | 0.8028 | 0.0000 |
| no_session_signals | 8 dropped | 0.8030 | +0.0002 |
| no_cash_gap_signals | 0 dropped | 0.8028 | 0.0000 |

## 5. Adoption Sensitivity & Simulated Loss Prevented

- Total simulated test skimming loss: **18,727.58 BDT** across **326 skimmer actions**.
  - Fee overcharges: 2,485.21 BDT
  - Payout reductions: 16,242.37 BDT

| Sathi Mandate Adoption | Cashouts Protected Without PIN | Skimming Loss Prevented (BDT) | Protection Rate |
|---|---|---|---|
| 30% Adoption | 30% | 5,618.27 BDT | 30% |
| 50% Adoption | 50% | 9,363.79 BDT | 50% |
| 70% Adoption | 70% | 13,109.31 BDT | 70% |

## 6. Robustness under Distribution Shift

| Dataset Split | PR-AUC | ROC-AUC | Brier Score | Recall @ 80% Precision |
|---|---|---|---|---|
| Canonical Test (Seed 2026) | 0.8049 | 0.8997 | 0.0892 | 0.8979 |
| Distribution-Shifted Test | 0.8437 | 0.8596 | 0.1343 | 0.8625 |

**PR-AUC Delta**: `+0.0388` (Robust: `True`)

## 7. Demographic Fairness Audit

Target maximum TPR disparity gap: `<= 10.0%` across all protected demographic slices.

Observed global maximum TPR gap: **`9.20%`** (Fairness Target Satisfied: **`True`**)

| Demographic Slice | Category | Sample Count | True Positive Rate (TPR) | False Positive Rate (FPR) | Review Rate |
|---|---|---|---|---|---|
| gender | female | 1294 | 0.9035 | 0.1086 | 0.3887 |
| gender | male | 1392 | 0.8994 | 0.1072 | 0.3843 |
| gender | other | 1314 | 0.8775 | 0.1074 | 0.3752 |
| age_band | 18-25 | 1042 | 0.8848 | 0.1283 | 0.3868 |
| age_band | 26-40 | 989 | 0.8750 | 0.0934 | 0.3589 |
| age_band | 41-60 | 1008 | 0.8978 | 0.0991 | 0.3938 |
| age_band | 60+ | 961 | 0.9167 | 0.1088 | 0.3913 |
| region | barishal | 480 | 0.8951 | 0.1164 | 0.3792 |
| region | chittagong | 502 | 0.8927 | 0.0923 | 0.3745 |
| region | dhaka | 519 | 0.8947 | 0.1064 | 0.3950 |
| region | khulna | 528 | 0.8782 | 0.1299 | 0.4091 |
| region | mymensingh | 483 | 0.8603 | 0.1020 | 0.3830 |
| region | rajshahi | 512 | 0.9524 | 0.0872 | 0.3711 |
| region | rangpur | 471 | 0.8795 | 0.1180 | 0.3864 |
| region | sylhet | 505 | 0.9006 | 0.1105 | 0.3624 |
| urban_rural | rural | 1691 | 0.9001 | 0.1110 | 0.4335 |
| urban_rural | urban | 2309 | 0.8872 | 0.1056 | 0.3456 |

### Slice Disparity Gaps:
- **gender**: `2.60%` gap
- **age_band**: `4.17%` gap
- **region**: `9.20%` gap
- **urban_rural**: `1.30%` gap