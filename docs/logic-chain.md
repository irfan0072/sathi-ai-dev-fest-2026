# Idea Development Framework (9-step logic chain)

## Problem statement (guideline template)
For **older adults and first-time rural users who cannot operate their wallets alone**, **sharing their PIN with agents or relatives** causes **unauthorised access, overcharging and loss of trust**. We will build **Sathi, an AI-assisted delegation layer** that uses **synthetic transaction, session and agent data** to **issue scoped one-time mandates, verify intent in Bangla, and flag at-risk users and abnormal agents**, with success measured by **share of assisted cash-outs completed without PIN disclosure and simulated loss prevented**.

| # | Step | Our answer | Evidence / source |
|---|---|---|---|
| 1 | User | Primary: older, low-literacy or first-time wallet owner (e.g. allowance recipient). Secondary: agent, fraud/risk analyst. | Rural MFS and allowance-programme studies: users rely on agents/family and share PINs |
| 2 | Problem | PIN sharing is the only way to transact for some users; it enables theft; fraud models assume the owner is typing | Same studies; PRI survey: most fraud involves compromised PINs or impersonation |
| 3 | Why now | Bangla speech tech, cheap LLMs for explanation, interoperability push, tighter BB fraud rules | BB 2026 card-to-MFS circular; e-KYC guideline effective 1 Sep 2026 |
| 4 | Solution | Mandate engine + voice/keypad verification + assisted-user outreach + agent risk console | See architecture.md |
| 5 | AI role | Prediction (assisted-user classifier), detection (agent anomaly), generation (plain-language explanation) | evaluation-plan.md |
| 6 | Impact | % assisted cash-outs without PIN disclosure; simulated loss prevented; detection precision/recall | [Fill targets after baseline] |
| 7 | Data | 100% synthetic generator with injected patterns; documented assumptions; held-out agents | data/assumptions.md |
| 8 | Validation | Offline metrics vs rule baseline + adoption-sensitivity simulation; plan for a controlled pilot | evaluation-plan.md |
| 9 | Scale | Channel-agnostic API (app, USSD, SMS, IVR); governed anonymised data pilot with a few agents | architecture.md section 6 |

## Product readiness checklist (from guideline)
- [ ] Problem is frequent or economically meaningful
- [ ] AI adds value beyond a simple rule (show baseline comparison)
- [ ] Clear action after each prediction (outreach, review, deny, issue mandate)
- [ ] Business benefit measurable
- [ ] Validatable with future real data
- [ ] Privacy, fairness, explainability, security addressed
- [ ] Fits a real digital-service workflow
