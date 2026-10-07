# Sathi: three-minute demo script, 30-second fallback, Q&A and recording checklist

**One sentence:** a customer states the cash they received, on their own; suspicious evidence goes
to a human; an answer we cannot trust stays unresolved; the system keeps honest agents and the
customer's privacy safe. Hackathon concept for upay: not endorsed by upay. Synthetic data.

Run the working loop for real, before and during the talk:

```sh
SATHI_TEST_DATABASE_URL=postgresql://USER@localhost:5432/DISPOSABLE_DB \
  python scripts/demo_scenario.py          # prints each step and the HTTP result, writes docs/evidence/
```

## The three minutes

**0:00-0:20 Problem and customer (20 s).** "Older people, people who cannot read well and students on an
allowance hand their phone and PIN to an agent. A dishonest agent can hand back less cash than the
ledger says. After the cash-out the only evidence is what the customer remembers." Show the sign-in
screen with the label *Hackathon concept, synthetic data*.

**0:20-1:40 Complete protection and human follow-up (80 s).** Use the live console, three windows:

1. *Agent* records a cash-out of ৳700 (Cash-out page). The agent sees only "waiting", never a result.
2. *Customer handset panel* (phone width) rings. Label it honestly: "ordinary phone-call
   simulation; a real feature phone needs cellular voice coverage only, no app or mobile data".
   The call never says the amount. The customer *says* something unclear ("umm...") and the handset
   switches to **keypad only** (the speech box disappears; the provider is told `input=dtmf`).
3. The customer types **0700#** (a leading zero is the silent help signal) and hears the same
   neutral ending as for any other answer.
4. *Supervisor* opens **Call queue -> Independent follow-up**: the help-signal task is **urgent** and
   first, above an ordinary mismatch. The follow-up panel does not offer "reached independently" for
   the registered number ("the agent may hold that phone"). *Analyst* opens the case: the page says
   up front that clearing needs an independent contact; pressing **Cleared: no wrongdoing** is refused
   (HTTP 409). Record an in-person contact (simulated in the demo; a real one is pending), then decide.
5. Show separately, each in a few seconds: a **matching** answer (verified, no case), an **unanswered**
   call (retry, then "Customer not reached", never "answered"), and **star** = the explicit
   "I did not make this" key (an empty answer or a lone # is silence, never a denial).
6. `scripts/demo_scenario.py` prints every step with its HTTP result if the live demo fails.

**1:40-2:20 Quantified AI improvement with denominators (40 s).** Open `docs/evaluation-agent-v2.md`.
"The canonical test had 60 agents and 2 skimmers, so we built an independent synthetic benchmark:
3 replications x 3,000 new agents, protocol written before any data, development and final cohorts
separate, final cohorts scored once. Final: **120 skimmers, 3,480 honest agents, 240 honest
high-volume**. Moderate skimming: the deployed ensemble flags **120/120** with **0/3,480** honest false
flags, the fee-ratio rule baseline **0/120**. But honest agents have zero fee noise in our simulator, so
this is an easy synthetic task. **Subtle skimming: 0/120, still missed** at the fixed threshold.
Unchanged-fee cash shortfalls: the ensemble flags **0/120**; a development-selected shortfall
scorer flags **119/120** but is not deployed. Threshold recall and precision-at-15 are different
policies with different denominators."

**2:20-2:45 Cost and evidence status (25 s).** "Observed in this synthetic run, from the database:
calls attempted, answered and completed with their denominators (Workflow evidence page). Cost per
1,000 cash-outs is an assumption model: the first report's all-call scenario is -৳506; with failed
attempts and case follow-up modelled, a detection-only workflow is negative. We do not count
flagged cases as recovered money. No real pilot data exists."

**2:45-3:00 Limits and the precise ask (15 s).** "Everything is synthetic. Pending, external: a
governed cash-out/KYC feed, a local IVR contract, consented usability tests, an independent security
review, and a supported intervention path. We ask for a sandbox and a 50-agent pilot under the
gates in `docs/pilot-partner-request.md`."

## 30-second fallback (no live system)

"Sathi asks the customer, after a cash-out, how much cash they received, without saying the
amount. A mismatch or the silent help signal opens a case for a person. Because the phone may be
in the agent's hand, a case cannot be cleared until an independent contact reaches the customer.
On 3 x 3,000 synthetic agents the detector separates moderate skimmers well, misses subtle ones at
the fixed threshold, and the economics are negative unless a separate intervention returns money.
All of it is synthetic; we need a governed pilot to know more."

## Likely judge questions (realistic answers)

- **Does it work on a feature phone with no mobile data?** The intended path is an ordinary
  cellular voice call: Bangla prompt, then spoken amount or keypad. Locally implemented and tested:
  keypad-only fallback (persisted, provider told `input=dtmf`), empty-callback-is-not-denial, `*` as
  explicit denial, urgent help-signal follow-up. Simulated here: the handset and the provider.
  Pending: a provisioned voice/IVR provider, Bangla audio, caller-number permission, and a field
  test. Without voice coverage the check stays pending and goes to a person; it is never confirmed.
- **What about USSD?** A separate service needing an operator or aggregator and an assigned code. Not
  built, no code invented. The adapter rules are in `docs/feature-phone-channels.md`.

- **Is the Bangla speech recognition fine-tuned?** No. The call provider transcribes; a word
  parser reads the amount afterwards. Approximate, conflicting or low-confidence speech goes to the
  keypad. It is not validated on regional or noisy speech; `docs/bangla-asr-evaluation-spec.md`
  defines the future test (WER/CER, exact amount, wrong-amount acceptance, abstention, p95 latency).
- **Does it prevent the loss?** No. The call happens after the cash-out. It detects, escalates and
  supports resolution. Prevention needs a hold or reversal that upay would have to provide.
- **What if the agent holds the customer's phone?** That is why a registered-number contact never
  counts as independent and a case cannot be cleared without an independent contact. The supervised
  in-person follow-up is a queue and status today; doing it for real is pending.
- **How many agents did you test?** The canonical cohort has 60 agents with 2 skimmers; the
  extended synthetic benchmark has 3,600 independent simulated agents in the final cohorts (120 skimmers, 240 honest high-volume). Subtle skimming still is not flagged at the fixed
  threshold. All synthetic, so it says nothing about real prevalence.
- **Why is precision at 15 different from recall?** Different policies: ranking a review budget
  versus flagging at a fixed risk threshold, with different denominators. We report both.
- **Is the audit log immutable?** It is an append-only trail: database triggers reject update,
  delete and truncate. A database owner can remove the triggers; there is no hash chain.
- **Is the public demo safe?** It is read-only for management and simulated-only, with published
  synthetic PINs. It is not a penetration test and there has been no independent review.
- **What does it cost?** `docs/economics-sensitivity.md`: an assumption model, with the negative
  all-call scenario and the break-even loss per incident. No invoices exist yet.
- **Which AI is deterministic?** Fixed rules decide verified/suspicious. The AI ranks agents and
  customers for human review and may draft a case summary; on the public demo the summary is
  deterministic.

## Recording checklist (the team records; this repository contains no video link)

1. Fresh disposable database, `scripts/demo_scenario.py` once to confirm the loop passes.
2. Start the API and console; sign in with the published synthetic PINs; show the label
   *Hackathon concept for upay, not endorsed by upay* and *Public simulated demo*.
3. Record the 80-second flow above in one take: agent, customer handset, supervisor.
4. Show the refusal of "reached independently via the registered number" and of clearing the case.
5. Show **Workflow evidence** with the numerators and denominators and the line "no field impact".
6. Say the limits and the ask. Keep it under 3:00; keep liquidity, uplift and scam features for Q&A.
7. Upload, test the link in a private window, and paste the URL into the report and README
   yourselves. Do not invent a link.
