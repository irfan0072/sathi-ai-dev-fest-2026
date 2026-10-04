# Idea development framework (9-step logic chain)

## Problem statement (guideline template)

For **older adults, allowance recipients and first-time rural users who need an agent to
cash out**, **handing over their phone and PIN** causes **hidden skimming, fee overcharging
and later misuse that they rarely notice or report**. We will build **Sathi, a confirmation
and risk layer** that uses **cash-out ledger, app-session and agent activity data (synthetic
in this prototype)** to **call the customer after every assisted cash-out, route mismatches
and risky agents to human review, and warn before risky payments**, with success measured by
**the share of assisted cash-outs confirmed by the customer, the confirmed skimming events
caught, and the false-flag rate on honest agents**.

| # | Step | Our answer | Evidence |
|---|---|---|---|
| 1 | User | Assisted customers (older adults, allowance recipients, first-time rural users); also agents, supervisors and analysts | [TIB, 27 May 2025](https://www.ti-bangladesh.org/images/2025/report/mfs/Executive-Summary-Mobile-Financial-Services-Sector-En.pdf); [Shitol et al., 21 Aug 2025](https://onlinelibrary.wiley.com/doi/10.1111/ijsw.70033) |
| 2 | Problem | PIN sharing gives agents reusable control; skimming and overcharging go unnoticed and unreported | TIB 2025: 6.3% of account holders were fraud victims; only 7.6% filed a case |
| 3 | Why now | Allowances are paid through MFS; 239 million accounts; cheap voice and AI make per-transaction confirmation affordable | Bangladesh Bank data, January 2025 |
| 4 | Solution | Confirmation call, silent duress code, voice mandate, operations center, send-money warnings | [architecture.md](architecture.md) |
| 5 | AI role | Prediction (assisted customers, liquidity), detection (agent anomaly, receiver risk), causal targeting (uplift), guarded generation (briefs, warnings) | [evaluation-results.md](evaluation-results.md) |
| 6 | Impact | Confirmed cash-outs, skimming caught, honest-agent false flags, cost per confirmation; break-even about ৳97 average loss per incident | Final report, section 8 |
| 7 | Data | Synthetic generator with documented assumptions, overlap and label noise; disjoint and shifted splits | [data/assumptions.md](../data/assumptions.md) |
| 8 | Validation | Baselines, ablations, distribution-shift test, fairness audit, adoption scenarios; pilot with stop-or-go gates | Final report, sections 7–8 |
| 9 | Scale | Channel-agnostic API; 5-million-customer test; governed-data pilot | [operations-center.md](operations-center.md) |
