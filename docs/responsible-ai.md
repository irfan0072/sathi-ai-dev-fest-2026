# Responsible AI and security

All data and transactions are synthetic. Financial figures are assumptions, not upay
figures. The AI only recommends; a person makes every decision.

| Principle | How Sathi meets it |
|---|---|
| Privacy | Synthetic data only; demographics are never model inputs; other people's numbers are masked in send money and the assistant; community reporters are stored as keyed hashes; report text is cleaned of phone numbers; provider credentials are encrypted at rest. **Call transcripts:** no audio is stored. The only free text kept from a call is the transcript, redacted of phone numbers, identifiers and long digit runs, capped at 200 characters and erased after `SATHI_TRANSCRIPT_RETENTION_DAYS` (default 30); the parsed outcome stays. Consent records and a subject-deletion process are not implemented (pending, needs a partner and a privacy review) |
| Explainability | SHAP reasons for customer scores, signal-level reasons for agent risk, plain-language advice and a "How this page works" guide on every AI page; case briefs cite evidence facts and say whether the text is deterministic or AI-written and pattern-checked |
| Fairness | Age, gender, region and urban/rural are used only to audit; maximum TPR gap 5.6% on the held-out test (target ≤ 10%); honest high-volume agents are measured explicitly |
| Security | Short-lived signed JWT with role and scope checks; a deactivated staff account's existing token stops working on the next request; PBKDF2-SHA256 PIN hashes; signed provider webhooks plus per-call tokens; one live call per check; row locks against double spending; `SATHI_DEPLOYMENT_MODE=public_demo` makes a public synthetic deployment read-only for management and pins providers to simulated. This is not a penetration test and there has been no independent review |
| Human oversight | Every suspicious result goes to a supervisor; assignment, notes, audit reports and a durable, append-only audit trail (database triggers reject UPDATE, DELETE and TRUNCATE on it). A database owner or superuser can still remove the triggers; there is no cryptographic hash chain, so the trail is not "immutable" |
| Transparency | Synthetic-data banner on every page; assumptions labelled; the frozen, reproducible evaluation is published in the console |
| No harmful automation | No automatic blocking or penalties; silence is never a denial; warnings say "appears in community alerts", never "scam"; the customer always decides |

## Boundaries

- No model approves, denies, blocks or delays a transaction. Verified or suspicious comes
  from the customer's answer compared with the ledger.
- The watchlist forces confirmation calls for an agent; it never blocks.
- Forecasts never limit a customer's cash-out. Outreach scores are used only to offer help.
- A cited fact ID only proves that the reference exists. Case-brief text is therefore checked
  in every field (secrets such as PIN/OTP, phone numbers, accusations, invented amounts,
  spelled-out money, numbers that are not in the cited facts, "held/recovered" claims on a
  completed cash-out, contradicted amount claims, customer questions that name the amount or
  the help signal). A failing brief is discarded and a deterministic template, built from typed
  evidence, is used. These are pattern checks: they cannot prove that a sentence means what its
  fact means, and the response says so. An external model only receives a minimised allowlist of
  facts (no identifiers, timestamps or free text). On a public deployment no external model is
  called at all.
- The primary cash-out has already completed when the confirmation call is made. Sathi detects
  and supports resolution; it does not hold, block or recover that money. Prevention needs a
  separately supported intervention that does not exist in the prototype.
- A confirmation cannot prove physical cash delivery or who answered the phone.
- **Independent follow-up.** The call goes to the registered number, which may be the handset the
  agent holds. A suspicious check therefore needs an independent follow-up (status `required`,
  `attempted`, `reached_independently`, `uncertain`, `unreachable`). Calling the registered number
  can never count as independent, no phone number is accepted from anyone, `uncertain` and
  `unreachable` keep the case open, and a case cannot be cleared before an in-person contact
  reached the customer. The queue exists and is tested; the supervised in-person follow-up itself
  is pending (external).
- Retry wording no longer announces a mismatch. Call length, an extra retry prompt, SMS and
  screens can still differ, so this limits the claim to the wording, not the whole interaction.
- Speech: a provider transcript plus a word parser, not a custom ASR model. Approximate,
  alternative or conflicting amounts, a missing or non-finite confidence and a wrong data type
  are "unclear" and go to the keypad. Not validated for regional or noisy Bangla
  (`docs/bangla-asr-evaluation-spec.md`).

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Agent watches the customer answer | Prompt never states the amount; silent `0` code; agent sees only "Confirmation done" |
| Agent answers on the customer's phone | Calls go to the registered number; cash gaps raise agent risk; random human callbacks planned for a pilot |
| Forged webhooks or replayed codes | Signature checks, per-call tokens, hashed one-time codes, replay rejection, attempt limits |
| False or malicious community reports | Moderation, rate limits, one "me too" per customer, non-accusatory wording |
| Prompt injection into the LLM | Only a minimised allowlist of structured facts is sent; schema, citation, per-field text guards, number grounding; template fallback; no external model on a public deployment |
| Model drift | Shifted-data tests, 15-minute live re-scoring, human review of every flag |

## Limits

Synthetic distributions cannot establish real-world accuracy or prevented loss. The canonical
agent cohort is small (2 skimmers); the extended benchmark (`docs/evaluation-agent-v2.md`) has
larger denominators but is still synthetic and shows that subtle skimming is not flagged at the
fixed threshold. Adoption scenarios assume perfect compliance and the economics are assumptions
(`docs/economics-sensitivity.md`). A governed pilot, a consent process and an independent
security review are required before any real deployment.
