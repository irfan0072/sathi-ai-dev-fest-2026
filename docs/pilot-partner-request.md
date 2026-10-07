# Sathi: partner and pilot request (PLANNED, not started)

**Status: planned.** Nothing below has happened. This page turns the missing evidence into a
concrete request. It does not replace the evidence. No call, SMS or data transfer was made to
write it. Written for Team Runtime Terrors, AI DEV FEST 2026. Sathi is a hackathon concept; this
request does not imply endorsement by upay.

## What we ask of a partner (upay, an MFS operator or a licensed IVR provider)

| Need | Why | Today |
|---|---|---|
| **Governed cash-out and KYC event feed** (authenticated, signed, idempotent; sandbox first) | The prototype's only cash-out entry is the agent API. A provider-recorded cash-out must never debit the ledger again. | Simulated. Contract unconfirmed |
| **Local IVR with Bangla prompts, keypad capture and signed webhooks** | Real answer, drop-off and cost numbers | A vendor-neutral JSON adapter and a local stand-in exist. Vendor contract unconfirmed |
| **Consent and privacy review** (transcript text, retention, deletion, no audio retained) | The prototype stores redacted transcript text for 30 days by default | Implemented locally. No consent records or DSAR process |
| **Independent security review** (not a self-assessment) | The prototype has only its own tests | None. Not a penetration test |
| **A supported intervention path** (hold, reversal, restitution) | The call happens after the cash-out. Detection alone recovers nothing | Not available. Not claimed |

## Exploratory usability tasks (needs consenting participants; none recruited)

Five to eight older, rural, low-literacy or allowance-recipient customers and five agents, with a
consent form and a local facilitator. Tasks: (1) answer a confirmation call and say or type the
cash received, (2) recognise and use the help signal, (3) ask for a person (key 9), (4) tell what
the call asked for and what it never asks for (PIN/OTP). Record completion, errors, drop-off and
comprehension, not opinions about the product. These are exploratory and cannot support a rate.

## Real outcomes to define before any number is reported

- **Answered**: the customer reached an answer step. **Completed**: a clear outcome (match,
  mismatch, denial, help signal). **Unclear**: not understood after one re-ask.
- **Customer-reported shortfall**, **supervisor-confirmed finding**, **restitution paid**,
  **appeal or reversal**: tracked separately. A flagged gap or a closed case is none of them.
- Cost per attempt, per answered call and per resolved case from real invoices and logged
  handling time (the repository's model uses stated assumptions only).

## Go / no-go gates (proposed)

| Gate | Go only if |
|---|---|
| 0 Sandbox replay (2 weeks) | Governed, anonymised data; models beat the rule baseline on real labels; privacy and security review passed |
| 1 Small pilot (8 weeks, ~50 agents, consenting customers) | Answer rate at least 60%; completion at least 70% of answered; honest-agent false suspicious at most 2%; 90% of cases reviewed in 24 h; complaints at most 1%; opt-out at most 15%; cost at most ৳2.50 per confirmation; no harm from help-signal handling |
| 2 Randomised scale-up | Confirmed events down at least 30% against control agents; net benefit positive under a measured intervention rate |

Stop and fix on any harm signal, any disclosure of the help signal to a bystander, or any
unconsented data use.

## What the team can show today instead (all local and synthetic)

`scripts/demo_scenario.py` (end-to-end workflow with numerators and denominators),
`docs/evaluation-agent-v2.md` (independent synthetic agent benchmark),
`docs/economics-sensitivity.md` (assumption model with the negative cases visible),
`docs/judge-feedback-traceability.md` (every judge request mapped to a status).
