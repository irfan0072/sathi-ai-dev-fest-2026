# Sathi Evaluation & Experimentation Results

> [!NOTE]
> All evaluations use synthetic MFS simulation data generated with disjoint cohorts
> per `docs/evaluation-plan.md` (Train Seed 42, Val Seed 4242, Test Seed 2026).
> Zero protected demographic features or ground truth labels were included in models.

## 1. Assisted-User Classifier vs Rule Baseline

> PR-AUC metric convention: `sklearn.metrics.auc(recall, precision)`.

| Cohort / Split | Model | PR-AUC | ROC-AUC | Brier Calibration | Recall @ 80% Prec |
| --- | --- | --- | --- | --- | --- |
| Validation (Diagnostic) | Rule Baseline | 0.6968 | 0.7133 | 0.2988 | 0.0000 |
| Validation (Diagnostic)* | Sathi LightGBM | 0.8145 | 0.8975 | 0.0939 | 0.8943 |
| **Held-out Test (2026)** | Rule Baseline | 0.6967 | 0.7134 | 0.2983 | 0.0000 |
| **Held-out Test (2026)** | **Sathi LightGBM (Held-out)** | **0.8091** | **0.9032** | **0.0898** | **0.8964** |

_*Validation metrics are calibration-cohort diagnostics and do not represent independent calibrated generalization; test cohort is held-out estimate._

### Noise Sensitivity Comparison:
| Configuration | Label Noise Level | PR-AUC | Recall @ 80% Prec |
| --- | --- | --- | --- |
| Configured 10% baseline label noise (not claimed pristine) | Baseline 10% | 0.8091 | 0.8964 |
| Extra 5% independent label flips beyond baseline 10% noise | Baseline 10% | 0.8119 | 0.9000 |

## 2. Agent Anomaly Detection: Ensemble & Baseline Comparison

| Method | Precision@15 | Recall on Skimmers | Honest High-Volume False Flags |
| --- | --- | --- | --- |
| Rule Baseline | 0.13 | 0.00 | 0.00 |
| Peer Robust Z-Score | 0.13 | 1.00 | 0.00 |
| Isolation Forest | 0.13 | 1.00 | 0.00 |
| **Combined Ensemble (0.7 Z + 0.3 IF)** | **0.13** | **1.00** | **0.00** |

## 3. Skimming Intensity Sweep

| Intensity | Skimmer Mean Risk | Honest Mean Risk | Skimmer Detection Rate | Honest False Flag Rate |
| --- | --- | --- | --- | --- |
| Subtle | 0.267 | 0.074 | 0.0% | 0.0% |
| Moderate | 0.916 | 0.073 | 100.0% | 0.0% |
| Obvious | 1.000 | 0.074 | 100.0% | 0.0% |

## 4. Signal Ablations

### Assisted Classifier Session Signals Ablation:
| Configuration | Features Dropped | PR-AUC | Delta vs Full |
| --- | --- | --- | --- |
| Full Behavioral Model | 0 | 0.8145 | 0.0000 |
| No Session Signals | 8 dropped | 0.8014 | -0.0131 |

### Agent Detector Cash-Report Ablation:
| Configuration | Precision@K | Recall on Skimmers |
| --- | --- | --- |
| Full Detector (with Cash Gap) | 0.13 | 1.00 |
| Ablated Detector (no Cash Gap) | 0.13 | 1.00 |

## 5. Adoption Sensitivity & Simulated Loss Prevented

> Idealized simulation assumption: counterfactual cashouts restricted to assisted simulated behavior users under hypothetical perfect mandate compliance. No claim of observed field impact.

- Total injected test skimming loss: **18,727.58 BDT**.
- Eligible assisted behavior customer loss: **14,802.26 BDT**.

| Adoption Assumption | Loss Prevented (BDT) | % Eligible Prevented | % Total Injected Prevented |
| --- | --- | --- | --- |
| 30% Adoption | 4,440.68 BDT | 30% | 23.7% |
| 50% Adoption | 7,401.13 BDT | 50% | 39.5% |
| 70% Adoption | 10,361.58 BDT | 70% | 55.3% |

## 6. Distribution Shift Robustness

| Cohort | Method | Precision | Recall | PR-AUC | Brier |
| --- | --- | --- | --- | --- | --- |
| Canonical test (seed2026) | Rule baseline | 0.5545 | 0.7521 | not defined | not defined |
| Canonical test (seed2026) | LightGBM | 0.8314 | 0.8914 | 0.8091 | 0.0898 |
| Shifted test (seed2026, separate distribution) | Rule baseline | 0.6728 | 0.7360 | not defined | not defined |
| Shifted test (seed2026, separate distribution) | LightGBM | 0.8403 | 0.8500 | 0.8185 | 0.1362 |

| Agent cohort | Method | n | Skimmers | Honest high volume | Top-K | Precision@K | Recall | Honest HV false flags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| canonical_test | baseline_rule | 60 | 2 | 4 | 15 | 0.1333 | 0.0000 | 0.0000 |
| canonical_test | peer_robust_zscore | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.0000 |
| canonical_test | isolation_forest | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.0000 |
| canonical_test | combined_ensemble | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.0000 |
| shifted_test | baseline_rule | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.0000 |
| shifted_test | peer_robust_zscore | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.0000 |
| shifted_test | isolation_forest | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.7500 |
| shifted_test | combined_ensemble | 60 | 2 | 4 | 15 | 0.1333 | 1.0000 | 0.0000 |

## 7. Demographic Fairness Audit

### validation_diagnostic

Validation is a calibration diagnostic; test cohorts are held-out estimates.
Configured TPR gap target: 0.1000.
Maximum gap: 0.09204575685022609; target status: True.

| Slice | Category | n | Positive | Negative | Method | TPR | FPR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gender | female | 1294 | 456 | 838 | rule_baseline | 0.7456 | 0.3186 |
| gender | female | 1294 | 456 | 838 | model | 0.9035 | 0.1086 |
| gender | male | 1392 | 487 | 905 | rule_baseline | 0.7577 | 0.3392 |
| gender | male | 1392 | 487 | 905 | model | 0.8953 | 0.1050 |
| gender | other | 1314 | 457 | 857 | rule_baseline | 0.7571 | 0.3221 |
| gender | other | 1314 | 457 | 857 | model | 0.8731 | 0.1074 |
| age_band | 18-25 | 1042 | 356 | 686 | rule_baseline | 0.7303 | 0.3222 |
| age_band | 18-25 | 1042 | 356 | 686 | model | 0.8848 | 0.1283 |
| age_band | 26-40 | 989 | 336 | 653 | rule_baseline | 0.7351 | 0.3047 |
| age_band | 26-40 | 989 | 336 | 653 | model | 0.8690 | 0.0919 |
| age_band | 41-60 | 1008 | 372 | 636 | rule_baseline | 0.7527 | 0.3412 |
| age_band | 41-60 | 1008 | 372 | 636 | model | 0.8952 | 0.0975 |
| age_band | 60+ | 961 | 336 | 625 | rule_baseline | 0.7976 | 0.3408 |
| age_band | 60+ | 961 | 336 | 625 | model | 0.9137 | 0.1088 |
| region | dhaka | 519 | 190 | 329 | rule_baseline | 0.7842 | 0.3191 |
| region | dhaka | 519 | 190 | 329 | model | 0.8947 | 0.1064 |
| region | chittagong | 502 | 177 | 325 | rule_baseline | 0.7514 | 0.3508 |
| region | chittagong | 502 | 177 | 325 | model | 0.8757 | 0.0923 |
| region | rajshahi | 512 | 168 | 344 | rule_baseline | 0.7321 | 0.3314 |
| region | rajshahi | 512 | 168 | 344 | model | 0.9524 | 0.0872 |
| region | khulna | 528 | 197 | 331 | rule_baseline | 0.7107 | 0.3323 |
| region | khulna | 528 | 197 | 331 | model | 0.8782 | 0.1269 |
| region | barishal | 480 | 162 | 318 | rule_baseline | 0.7531 | 0.3208 |
| region | barishal | 480 | 162 | 318 | model | 0.8951 | 0.1195 |
| region | sylhet | 505 | 161 | 344 | rule_baseline | 0.7516 | 0.3314 |
| region | sylhet | 505 | 161 | 344 | model | 0.8944 | 0.1076 |
| region | rangpur | 471 | 166 | 305 | rule_baseline | 0.7590 | 0.3344 |
| region | rangpur | 471 | 166 | 305 | model | 0.8795 | 0.1180 |
| region | mymensingh | 483 | 179 | 304 | rule_baseline | 0.7877 | 0.2928 |
| region | mymensingh | 483 | 179 | 304 | model | 0.8603 | 0.0987 |
| urban_rural | urban | 2309 | 709 | 1600 | rule_baseline | 0.7504 | 0.3125 |
| urban_rural | urban | 2309 | 709 | 1600 | model | 0.8829 | 0.1044 |
| urban_rural | rural | 1691 | 691 | 1000 | rule_baseline | 0.7569 | 0.3500 |
| urban_rural | rural | 1691 | 691 | 1000 | model | 0.8987 | 0.1110 |

### held_out_canonical

Validation is a calibration diagnostic; test cohorts are held-out estimates.
Configured TPR gap target: 0.1000.
Maximum gap: 0.056038047973531846; target status: True.

| Slice | Category | n | Positive | Negative | Method | TPR | FPR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gender | female | 1283 | 431 | 852 | rule_baseline | 0.7819 | 0.3134 |
| gender | female | 1283 | 431 | 852 | model | 0.8933 | 0.0915 |
| gender | male | 1352 | 480 | 872 | rule_baseline | 0.7208 | 0.3452 |
| gender | male | 1352 | 480 | 872 | model | 0.8979 | 0.1044 |
| gender | other | 1365 | 489 | 876 | rule_baseline | 0.7566 | 0.3174 |
| gender | other | 1365 | 489 | 876 | model | 0.8834 | 0.0959 |
| age_band | 18-25 | 994 | 352 | 642 | rule_baseline | 0.7443 | 0.3287 |
| age_band | 18-25 | 994 | 352 | 642 | model | 0.8835 | 0.1012 |
| age_band | 26-40 | 965 | 343 | 622 | rule_baseline | 0.7668 | 0.3135 |
| age_band | 26-40 | 965 | 343 | 622 | model | 0.8921 | 0.0900 |
| age_band | 41-60 | 1009 | 344 | 665 | rule_baseline | 0.7645 | 0.3248 |
| age_band | 41-60 | 1009 | 344 | 665 | model | 0.8866 | 0.1023 |
| age_band | 60+ | 1032 | 361 | 671 | rule_baseline | 0.7341 | 0.3338 |
| age_band | 60+ | 1032 | 361 | 671 | model | 0.9030 | 0.0954 |
| region | dhaka | 464 | 156 | 308 | rule_baseline | 0.7500 | 0.3279 |
| region | dhaka | 464 | 156 | 308 | model | 0.8526 | 0.0617 |
| region | chittagong | 485 | 161 | 324 | rule_baseline | 0.7516 | 0.3272 |
| region | chittagong | 485 | 161 | 324 | model | 0.9068 | 0.1080 |
| region | rajshahi | 472 | 183 | 289 | rule_baseline | 0.7432 | 0.3287 |
| region | rajshahi | 472 | 183 | 289 | model | 0.8798 | 0.1107 |
| region | khulna | 518 | 186 | 332 | rule_baseline | 0.7634 | 0.3524 |
| region | khulna | 518 | 186 | 332 | model | 0.9086 | 0.0934 |
| region | barishal | 512 | 191 | 321 | rule_baseline | 0.7696 | 0.3333 |
| region | barishal | 512 | 191 | 321 | model | 0.8743 | 0.1028 |
| region | sylhet | 531 | 183 | 348 | rule_baseline | 0.7760 | 0.3132 |
| region | sylhet | 531 | 183 | 348 | model | 0.8962 | 0.1092 |
| region | rangpur | 516 | 181 | 335 | rule_baseline | 0.7624 | 0.2776 |
| region | rangpur | 516 | 181 | 335 | model | 0.9061 | 0.0896 |
| region | mymensingh | 502 | 159 | 343 | rule_baseline | 0.6918 | 0.3440 |
| region | mymensingh | 502 | 159 | 343 | model | 0.9057 | 0.1020 |
| urban_rural | urban | 2301 | 701 | 1600 | rule_baseline | 0.7589 | 0.3137 |
| urban_rural | urban | 2301 | 701 | 1600 | model | 0.9001 | 0.0869 |
| urban_rural | rural | 1699 | 699 | 1000 | rule_baseline | 0.7454 | 0.3440 |
| urban_rural | rural | 1699 | 699 | 1000 | model | 0.8827 | 0.1140 |

### held_out_shifted

Validation is a calibration diagnostic; test cohorts are held-out estimates.
Configured TPR gap target: 0.1000.
Maximum gap: 0.05386522425061979; target status: True.

| Slice | Category | n | Positive | Negative | Method | TPR | FPR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gender | female | 1331 | 674 | 657 | rule_baseline | 0.7493 | 0.3607 |
| gender | female | 1331 | 674 | 657 | model | 0.8383 | 0.1309 |
| gender | male | 1330 | 656 | 674 | rule_baseline | 0.7317 | 0.3442 |
| gender | male | 1330 | 656 | 674 | model | 0.8628 | 0.1706 |
| gender | other | 1339 | 670 | 669 | rule_baseline | 0.7269 | 0.3692 |
| gender | other | 1339 | 670 | 669 | model | 0.8493 | 0.1824 |
| age_band | 18-25 | 1033 | 526 | 507 | rule_baseline | 0.7376 | 0.3432 |
| age_band | 18-25 | 1033 | 526 | 507 | model | 0.8460 | 0.1598 |
| age_band | 26-40 | 971 | 470 | 501 | rule_baseline | 0.7319 | 0.3713 |
| age_band | 26-40 | 971 | 470 | 501 | model | 0.8468 | 0.1577 |
| age_band | 41-60 | 994 | 529 | 465 | rule_baseline | 0.7448 | 0.3634 |
| age_band | 41-60 | 994 | 529 | 465 | model | 0.8507 | 0.1441 |
| age_band | 60+ | 1002 | 475 | 527 | rule_baseline | 0.7284 | 0.3548 |
| age_band | 60+ | 1002 | 475 | 527 | model | 0.8568 | 0.1822 |
| region | dhaka | 504 | 261 | 243 | rule_baseline | 0.7318 | 0.3045 |
| region | dhaka | 504 | 261 | 243 | model | 0.8774 | 0.1481 |
| region | chittagong | 524 | 261 | 263 | rule_baseline | 0.7318 | 0.3916 |
| region | chittagong | 524 | 261 | 263 | model | 0.8621 | 0.1749 |
| region | rajshahi | 496 | 245 | 251 | rule_baseline | 0.7633 | 0.3705 |
| region | rajshahi | 496 | 245 | 251 | model | 0.8245 | 0.1355 |
| region | khulna | 526 | 255 | 271 | rule_baseline | 0.6941 | 0.4207 |
| region | khulna | 526 | 255 | 271 | model | 0.8549 | 0.2030 |
| region | barishal | 497 | 255 | 242 | rule_baseline | 0.7765 | 0.3223 |
| region | barishal | 497 | 255 | 242 | model | 0.8235 | 0.1198 |
| region | sylhet | 498 | 258 | 240 | rule_baseline | 0.7287 | 0.3625 |
| region | sylhet | 498 | 258 | 240 | model | 0.8450 | 0.1542 |
| region | rangpur | 477 | 230 | 247 | rule_baseline | 0.7130 | 0.3036 |
| region | rangpur | 477 | 230 | 247 | model | 0.8522 | 0.1579 |
| region | mymensingh | 478 | 235 | 243 | rule_baseline | 0.7489 | 0.3786 |
| region | mymensingh | 478 | 235 | 243 | model | 0.8596 | 0.1934 |
| urban_rural | urban | 2137 | 937 | 1200 | rule_baseline | 0.7236 | 0.3467 |
| urban_rural | urban | 2137 | 937 | 1200 | model | 0.8495 | 0.1725 |
| urban_rural | rural | 1863 | 1063 | 800 | rule_baseline | 0.7469 | 0.3750 |
| urban_rural | rural | 1863 | 1063 | 800 | model | 0.8504 | 0.1450 |
