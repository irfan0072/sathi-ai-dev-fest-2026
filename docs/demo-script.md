# Demo Video Script (target 3 to 4 minutes)

Must show how it works, features and AI components, and real-life value (rulebook 7.2).

| Time | Scene | Say / show |
|---|---|---|
| 0:00-0:25 | Problem | Rahima, 70, receives her allowance. She cannot use USSD alone, so she tells the agent her PIN. One line of evidence from the studies. |
| 0:25-0:50 | Idea | Sathi: scoped one-time mandate instead of PIN sharing. Show the architecture slide briefly. |
| 0:50-1:40 | Live flow | Agent terminal requests a 3,000 cash-out. Customer phone simulator shows the amount and fee; customer enters the amount with keypad/Bangla digits. Match -> verified; bound agent issues the one-time code (15 min, one agent, capped). Redeem and show actual receipt. |
| 1:40-2:05 | Failure path | Customer enters a different amount -> REVIEW case appears with reasons. Show human decision. |
| 2:05-2:50 | AI | Outreach list of likely assisted users with SHAP reasons; agent risk board with peer comparison; skimmer flagged using fee ratio and cash-received gap. |
| 2:50-3:25 | Evidence | Metrics page: baseline vs model, adoption sensitivity, fairness slices. State clearly it is synthetic. |
| 3:25-3:50 | Responsible and scale | Human review, no auto-decisions, audit log; channel-agnostic API; pilot path with governed data. |
| 3:50-4:00 | Close | State the synthetic counterfactual assumptions and the remaining real-world validation step. |

## Before recording
- [ ] Live URL works from a clean browser; seeded demo data loaded
- [ ] Keypad flow rehearsed (voice flow as bonus)
- [ ] Numbers on the metrics page match the report
- [ ] Captions or clear audio; Bangla text renders correctly

## Likely judge questions
1. Why not just a rule? -> baseline vs model numbers on held-out agents.
2. How would you validate with real data? -> controlled pilot path, anonymised or aggregated data.
3. What if an agent colludes? -> caps, logging, risk score, cash-received check, review.
4. What does AI decide? -> nothing final; rules and humans decide.
5. Is this new? -> accurate prior-art statement from the report.

## Audit-corrected recording gate (supersedes optimistic scene claims)

The customer character above is illustrative. Record keypad first; do not claim working voice recognition unless actually verified. At assumed3000BDT cash-out and1.5% fee, display45BDT fee and3045BDT debit before confirmation. Customer confirmation must not reveal the code; the bound agent terminal issues it after verification. Show actual ledger receipt after redemption and a replay rejection. Mismatch creates review; human review never automatically redeems.

Use final saved held-out results only. Current sample outreach/risk cards and unavailable metrics are unsuitable as completed AI evidence. Fairness misses and synthetic adoption assumptions must remain visible. No real upay rates, integration, customer identities or prevented-loss claims. Durable login/local API flow is verifiedT024; public URL, console wiring, metrics/report parity and rehearsal remain unchecked.
