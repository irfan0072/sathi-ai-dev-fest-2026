# Responsible AI and Security

## Mapping to guideline principles
| Principle | What we do | Evidence to show |
|---|---|---|
| Privacy | Synthetic data only; no real PII; store parsed amount, not voice audio | assumptions.md, schema |
| Explainability | SHAP and peer comparison for each flag | Console screenshots |
| Fairness | Slice metrics by gender, age band, region; those fields are not model inputs | evaluation report |
| Security | Hashed one-time codes, TTL, single use, rate limits, RBAC, audit log, prompt-injection tests | tests |
| Human oversight | REVIEW path for mismatches, caps, high agent risk; analysts approve or override | Case queue |
| Transparency | Predictions, assumptions and generated text are labelled separately | UI labels |
| No harmful automation | Models never approve or deny; policy rules plus humans decide; no automatic agent penalties | architecture.md |

## Threat model
| Threat | Mitigation |
|---|---|
| Replay or guessing of one-time code | Hash, TTL, single use, attempt lockout |
| Agent colludes with a fraudster | Caps, per-agent limits, agent risk, post-redeem cash confirmation, human review |
| Customer coerced or confused | System checks amount comprehension only; makes no claim to detect coercion; easy revoke; review on mismatch |
| Prompt injection via free text | Structured inputs, instructions separated from data, numeric checks, injection tests |
| Data leakage via copilot | Copilot receives only the fields needed for the case; no raw identifiers beyond tokens |
| Model drift / bias | Fairness slices, versioned models in audit log, retrain plan |
| Over-flagging honest agents | Honest high-volume agents in the test set; flags only prioritise review |

## Consent and data minimisation
- Each mandate records customer verification. Customers can revoke an active mandate.
- Keep only what is needed: parsed amount, outcome, timestamps, hashed code.

## Limitations to state openly
- Synthetic data and simulated impact; real validation needs governed upay data.
- Skimming is largely invisible in ledgers; results depend on indirect signals and customer cash-received reports.
- Voice recognition quality varies by speaker and noise; keypad is the reliable fallback.
