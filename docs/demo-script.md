# Sathi demo script — verified local fallback (3 minutes)

All characters, money and transactions are synthetic ASSUMPTIONS. No real upay integration. Rehearsed3October2026 using console13000/API18000 and preserved PostgreSQL. [Captioned walkthrough](demo-walkthrough.html), [MP4](demo-walkthrough.mp4), [captions](demo-walkthrough.srt). The video is assembled from actual UI captures rather than continuous real-time screen recording. Active codes are deliberately omitted. Organizer format/length acceptance remains unconfirmed.

| Time | Show and explain |
|---|---|
|0:00–0:20|Illustrative assisted customer; reusable PIN sharing gives excessive authority. Study is68 qualitative interviews in Kurigram, not national prevalence. Synthetic demo notice visible.|
|0:20–0:45|Agent role/PIN1234 requests3000BDT. Customer role/PIN5678 sees full payout3000, assumedfee45, totaldebit3045.|
|0:45–1:10|Enter৩,০০০ or use keypad; verified response exposes no code. Switch to bound agent; issue once, redeem. Repeat issuance/replay rejected; never show signing secrets.|
|1:10–1:30|Customer receipt from actual ledger, not physical-delivery proof. Report২,৮০০: gap200 exceeds assumed60 tolerance and creates human case.|
|1:30–1:50|New3000 request; customer2500 twice: requested after first mismatch, rejected after second, cases created. Analyst/PIN9012 escalates case; no redemption granted.|
|1:50–2:15|Outreach saved probability/reasons (SHAP raw log-odds); agent saved review score/train-derived volume peers. Neither score is authorization or proven fraud.|
|2:15–2:45|HeldoutPR0.8091/rule0.6967; model estimates full4000users. Agent2/2skimmers,0/4HV,precision@15=2/15; shiftedIFfalse3/4 and subtle0/2 disclosed. Adoption50% means idealized7401.13BDT eligible loss prevented, not measured benefit.|
|2:45–3:00|Fairnessheldoutgap5.604% vsassumed10% target on synthetic slices only. Governed pilot/security/channel validation remain. No STT/LLM/graph bonus claimed.|

## Rehearsal evidence

- [x] Real local API and console readiness pass; mock18001 unused.
- [x] Scoped in-memory login/role switching; customer cannot issue/read terminal code.
- [x] Bangla confirm → issue → redeem → ledger receipt; transactions424200038067/424200038068.
- [x] Duplicate issuance and replay rejected; active codes cleared after redemption.
- [x] Cash report2800/gap200/tolerance60/case5, durable human escalation.
- [x] Browser mismatch2500 twice → cases6/7/second rejected; attempts bounded by server.
- [x] Metrics equal committed results exactly; clear baseline/synthetic limitations/undefined values.
- [x] Bangla renders; captioned local walkthrough prepared and inspected.
- [ ] Public URLs/remote smoke and organizer-approved video format; human action pending.

At the start of a live demo, run `make smoke-skeleton`, open the console, sign in as agent and request a new mandate. Preserve the existing ledger: never reseed to refill balances. Initial50,000BDT is assumed and finite; daily25000BDT limit applies. A browser reload clears in-memory login/flow; receipt IDs and cases remain in PostgreSQL. Warm hostedhealth before judging if the human deploys. Current local receipt424200038068 remains available to its synthetic customer.
