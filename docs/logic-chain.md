# Idea Development Framework (9-step logic chain)

## Problem statement (guideline template)
For **older adults and first-time rural users who cannot operate their wallets alone**, **sharing their PIN with agents or relatives** can expose **reusable account authority beyond a single cash-out**. We will build **Sathi, an AI-assisted delegation layer** that uses **synthetic transaction, session and agent data** to **issue scoped one-time mandates, verify intent in Bangla, and flag at-risk users and abnormal agents**, with success measured by **share of assisted cash-outs completed without PIN disclosure and simulated loss prevented**.

| # | Step | Our answer | Evidence / source |
|---|---|---|---|
| 1 | User | Primary: wallet owners needing assistance, including allowance recipients. Secondary: agent and analyst. | [Shitol et al.(2025)](https://onlinelibrary.wiley.com/doi/10.1111/ijsw.70033):68 qualitative interviews in Kurigram describe reliance on help and PIN sharing; not a national prevalence estimate |
| 2 | Problem | Reusable PIN sharing can expose broader authority than a single withdrawal needs; this is our design inference. | Same study motivates assistance needs; no unsupported national fraud percentage claimed |
| 3 | Why now | Test a bounded delegation prototype with reproducible synthetic evidence and keypad confirmation. | Project rationale; no claim about unverified 2026 regulations or required speech/LLM capability |
| 4 | Solution | Mandate engine + voice/keypad verification + assisted-user outreach + agent risk console | See architecture.md |
| 5 | AI role | Prediction (assisted-user classifier), detection (agent anomaly), generation (plain-language explanation) | evaluation-plan.md |
| 6 | Impact | % assisted cash-outs without PIN disclosure; simulated loss prevented; detection precision/recall | [Fill targets after baseline] |
| 7 | Data | 100% synthetic generator with injected patterns; documented assumptions; held-out agents | data/assumptions.md |
| 8 | Validation | Offline metrics vs rule baseline + adoption-sensitivity simulation; plan for a controlled pilot | evaluation-plan.md |
| 9 | Scale | Channel-agnostic API (app, USSD, SMS, IVR); governed anonymised data pilot with a few agents | architecture.md section 6 |

## Product readiness checklist (from guideline)
- [ ] Problem is frequent or economically meaningful
- [ ] AI adds value beyond a simple rule (show baseline comparison)
- [ ] Clear action after predictions (outreach, human review); mandate authorization remains deterministic policy
- [ ] Business benefit measurable
- [ ] Validatable with future real data
- [ ] Privacy, fairness, explainability, security addressed
- [ ] Fits a real digital-service workflow
