# Demo Video Script (target 3 to 4 minutes)

Must show how it works, features and AI components, and real-life value (rulebook 7.2).

| Time | Scene | Say / show |
|---|---|---|
| 0:00-0:25 | Problem | Rahima, 70, receives her allowance. She cannot use USSD alone, so she tells the agent her PIN. One line of evidence from the studies. |
| 0:25-0:50 | Idea | Sathi: scoped one-time mandate instead of PIN sharing. Show the architecture slide briefly. |
| 0:50-1:40 | Live flow | Agent terminal requests a 3,000 cash-out. Phone simulator plays Bangla prompt; customer enters or says the amount. Match -> one-time code (15 min, one agent, capped). Redeem. Bangla receipt. |
| 1:40-2:05 | Failure path | Customer enters a different amount -> REVIEW case appears with reasons. Show human decision. |
| 2:05-2:50 | AI | Outreach list of likely assisted users with SHAP reasons; agent risk board with peer comparison; skimmer flagged using fee ratio and cash-received gap. |
| 2:50-3:25 | Evidence | Metrics page: baseline vs model, adoption sensitivity, fairness slices. State clearly it is synthetic. |
| 3:25-3:50 | Responsible and scale | Human review, no auto-decisions, audit log; channel-agnostic API; pilot path with governed data. |
| 3:50-4:00 | Close | The impact in one sentence with the main number. |

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
