# Responsible AI and security

All data and transactions are synthetic. Financial figures are assumptions, not upay
figures. The AI only recommends; a person makes every decision.

| Principle | How Sathi meets it |
|---|---|
| Privacy | Synthetic data only; demographics are never model inputs; other people's numbers are masked in send money and the assistant; community reporters are stored as keyed hashes; report text is cleaned of phone numbers; provider credentials are encrypted at rest |
| Explainability | SHAP reasons for customer scores, signal-level reasons for agent risk, plain-language advice and a "How this page works" guide on every AI page; LLM briefs must cite evidence facts |
| Fairness | Age, gender, region and urban/rural are used only to audit; maximum TPR gap 5.6% on the held-out test (target ≤ 10%); honest high-volume agents are measured explicitly |
| Security | Short-lived signed JWT with role and scope checks; PBKDF2-SHA256 PIN hashes; signed provider webhooks plus per-call tokens; one live call per check; row locks against double spending |
| Human oversight | Every suspicious result goes to a supervisor; assignment, notes, audit reports and a full audit log |
| Transparency | Synthetic-data banner on every page; assumptions labelled; the frozen, reproducible evaluation is published in the console |
| No harmful automation | No automatic blocking or penalties; silence is never a denial; warnings say "appears in community alerts", never "scam"; the customer always decides |

## Boundaries

- No model approves, denies, blocks or delays a transaction. Verified or suspicious comes
  from the customer's answer compared with the ledger.
- The watchlist forces confirmation calls for an agent; it never blocks.
- Forecasts never limit a customer's cash-out. Outreach scores are used only to offer help.
- LLM output is discarded if it is ungrounded, accusatory or contains phone numbers; a
  deterministic template is used instead.
- A confirmation cannot prove physical cash delivery or who answered the phone.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Agent watches the customer answer | Prompt never states the amount; silent `0` code; agent sees only "Confirmation done" |
| Agent answers on the customer's phone | Calls go to the registered number; cash gaps raise agent risk; random human callbacks planned for a pilot |
| Forged webhooks or replayed codes | Signature checks, per-call tokens, hashed one-time codes, replay rejection, attempt limits |
| False or malicious community reports | Moderation, rate limits, one "me too" per customer, non-accusatory wording |
| Prompt injection into the LLM | Only structured facts are sent; schema, citation, accusation and number checks; template fallback |
| Model drift | Shifted-data tests, 15-minute live re-scoring, human review of every flag |

## Limits

Synthetic distributions cannot establish real-world accuracy or prevented loss. Agent
results rest on small samples, and subtle skimming is not detected. Adoption scenarios
assume perfect compliance. A governed pilot is required before any real deployment.
