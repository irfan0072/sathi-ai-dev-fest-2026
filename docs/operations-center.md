# Operations center: roles, call management and case work

Sathi runs as a multi-role fraud operations system for upay. Every number on every screen
is read live from PostgreSQL. Nothing comes from a frozen snapshot. The only fixed numbers
are on the "AI test results" page: the offline held-out evaluation, kept fixed on purpose so
anyone can reproduce it.

## Roles

| Capability | Agent | Customer | Supervisor | Super admin | Fraud analyst |
|---|---|---|---|---|---|
| Record cash-out | yes | | | | |
| Answer confirmation call | | yes | | | |
| My desk (own workload) | | | yes | | |
| Call queue: pending list, claim, log outcome | | | yes | yes (any call) | |
| Assign calls/cases to a named supervisor, share evenly | | | | yes | |
| Escalate ignored/retrying calls to people | | | | yes | |
| Cases: claim, notes (message / critical / call log), audit report | | | own cases | any case | legacy decision |
| AI case brief | | | yes | yes | yes |
| Control center (live platform analytics) | | | | yes | |
| Customers / agents / staff directories | | | | yes | |
| All transactions (live ledger) | | | | yes | |
| Audit log, audit reports | | | own reports | yes | |
| Staff management (create, deactivate, reset PIN) | | | | yes | |
| Settings (providers, credentials, policy), live traffic simulator | | | | yes | |
| Fraud dashboard, agent risk AI, liquidity, uplift | | | | yes | yes |

The backend enforces every row with `require_roles` and ownership checks. Supervisors get
`403` on admin surfaces, and `403 NOT_YOURS` when they act on work assigned to someone else.
Claims are one conditional `UPDATE ... WHERE assigned_to IS NULL`. Two supervisors can never
take the same call or case; the second one gets `409 ALREADY_TAKEN`.

Staff accounts live in the `staff` table with salted PBKDF2 PIN hashes. A super admin can
add supervisors from the Supervisors page. Deactivating a supervisor blocks their next
sign-in and hands their open calls and cases back to the shared queue.

## Call management lifecycle

Each post-cash-out check gets one `call_tasks` row:

```
auto ──no answer──▶ retry_scheduled ──(delay, doubling)──▶ auto ...   up to N automatic calls
  │                       └── N calls used ──▶ ignored  (check = unreachable)
  ├── answer not understood twice ──▶ needs_manual ──claim / assign──▶ assigned ──▶ in_progress ──▶ resolved
  └── clear answer ──▶ resolved (verified, or suspicious + automatic case)
```

- **Missed calls.** Real providers report `no-answer`/`busy` through their status webhook.
  Demo calls time out after the configured ring time. The background scheduler places the
  retry when it is due. It claims due rows with `FOR UPDATE SKIP LOCKED`, so several API
  replicas never call the same customer twice.
- **Ignored.** After `calls.max_auto_attempts` misses (default 3), the task becomes
  `ignored` and the check becomes `unreachable`. A super admin can still send it to the
  supervisors.
- **Not understood.** Keypad input with `*`, zero or too many digits counts as unclear. So
  does a spoken answer below `calls.unclear_confidence`, or one that does not parse as an
  amount (Bangla digits and number words are supported). The system asks once more and then
  sends the call to the manual queue. It never guesses an amount.
- **Every answer is recorded** in `call_responses`: the raw input, how it was understood,
  the amount, the recognition confidence, and who recorded it (`sathi-ivr` or the supervisor).
- **Supervisor outcome.** The outcomes are confirmed, different amount, denied, duress,
  call back later and unreachable. A typed amount is compared with the ledger on the server.
  Different amount, denied and duress open a case automatically, with the supervisor's call
  note attached as a `call_log` note.

Policy settings (Settings → Call management): max automatic attempts, first retry delay,
ring timeout, and speech confidence threshold.

## Case work

Suspicious checks open cases. Supervisors take cases from the pending list, or a super
admin assigns them or shares the queue evenly by current load. Notes have a type:
`message`, `critical` (flagged on the desk of every supervisor) or `call_log`. A case closes
with an **audit report** that records findings, action taken, recommendation, risk level,
whether the customer was contacted, and the decision (cleared / problem confirmed /
escalated). The report also writes `review_actions`, a case note and an audit-log entry.

## Live AI (no frozen snapshots)

| Page | What runs live |
|---|---|
| Agent risk (AI) | The trained agent anomaly model (`agent.joblib`) scores every agent with activity in the last 30 days. Features are aggregated in PostgreSQL: fee charged vs the official rate, daily volume, allowance-day spikes. A cash gap a customer reports on their confirmation call counts as the agent's cash-report feature. Refreshed every 2 minutes. |
| Customers who need help | The trained assisted classifier (`assisted.joblib`) scores customers with app/USSD activity in the last 30 days from their live transactions and sessions. Per-customer SHAP reasons are computed on demand. |
| Cash planning | LightGBM point and P90 models are re-trained every 15 minutes on the last 90 days of live cash-outs. They forecast the next 7 real days for the 2,500 busiest agents; other agents get the peer-cohort forecast. |
| Invite planner | The uplift T-learner is re-trained on live customer features. Campaign outcomes still come from the documented experiment simulator until upay runs a real campaign. |

A background thread recomputes these results. Pages always get the latest finished result
and never wait for a re-train.

**Ledger time alignment.** The generated training cohorts were simulated on a timeline that
ran into the future (to 2026-12-29), so "last 24 hours" windows were empty. At startup,
`app/live/rebase.py` shifts those cohort rows back by whole days so the history ends today.
Whole days keep weekdays and the allowance cycle intact. The shift is recorded once in the
audit log (`ledger_rebased`) and the agent model uses it to locate allowance days. Live
rows are never moved.

## Live traffic simulator

Control center → Live traffic simulator (or `PUT /api/v1/admin/simulator`). The simulator
records synthetic cash-outs at the chosen rate and answers their calls with a realistic mix
of behaviours:

- about 64% confirm,
- about 15% miss the call,
- about 8% mumble and go to a supervisor,
- about 6.5% dispute the amount,
- about 4% deny,
- about 1% confirm on the second try,
- about 1% use the secret help signal.

Each simulated cash-out goes through the real ledger, call, interpretation, case and queue
code. Real rules (balance, daily limit) still apply.

## Scale (5 million customers)

`make scale-seed` loads 5,000,000 synthetic customers in the reserved `U_9_` namespace into
PostgreSQL in batches, with `generate_series`. It also creates 20,000 agent points (one per
250 customers), and 1.5% of those agents overcharge the fee. Each customer gets an opening
credit, and about 40% also get a cash-out at their home agent within 48 hours. Measured on a laptop Docker PostgreSQL 16:
5.02 M customers and 7.19 M transactions loaded in 675 s.

| Endpoint (super admin) | Warm latency |
|---|---|
| `GET /admin/overview` | 0.16 s |
| `GET /admin/users?limit=50` (keyset) | 0.15 s |
| `GET /admin/users?q=U_9_0042` (prefix) | 0.05 s |
| `GET /admin/transactions?limit=50` | 0.04 s |
| `GET /admin/agents?limit=50` (30-day stats per agent) | 0.4–1.2 s |
| `GET /callcenter/stats` | 0.10 s |

These patterns keep the system fast at this size:

- Every list uses keyset pagination on an indexed key, never `OFFSET`.
- Big-table totals come from planner statistics (`pg_class.reltuples`), not `count(*)`.
- Time-window aggregates use the `ts` / `created_at` indexes from migration 008.

## Demo walk-through

1. Sign in as **Super admin** (`demo_admin` / 7890), open the Control center, and start
   the simulator at 30/min. Tiles and charts update every 5 seconds.
2. Open **Call management** to see retries, ignored customers and "needs a person" items.
   Click **Share pending calls evenly**.
3. Sign in as **Supervisor** `sup_nadia` / 3456. My desk shows the assigned calls. Open the
   call queue, start a call, record "Customer got a different amount" with a note, and see
   the automatic case.
4. In **Cases**, take the case, add a critical note, and file the audit report.
5. Back as super admin, the report appears in **Audit reports**, the supervisor workload
   updates in **Supervisors**, and every step is in the **Audit log**.

## Languages: Bangla, English, Banglish

`app/lang/detect.py` sorts every customer message or spoken answer into one of three
languages. Bengali script counts as Bangla. Latin text counts as Banglish when a quarter or
more of its words are common romanized Bangla words; otherwise it counts as English.

Sathi stores each customer's language in `customer_prefs`. It learns the language from what
the customer writes in chat, what they say on calls, and when they press 8. A choice the
customer makes on My account always wins over a learned guess. The next confirmation call
and every assistant reply use that language.

## Human-friendly confirmation calls

The call scripts in `app/voice/scripts.py` follow these rules in all three languages:

- Sathi greets the customer and says who is calling and why before asking anything.
- The call never says the amount, the balance or the agent. It never asks for a PIN.
- Every outcome ends with the same closing sentence, so a bystander learns nothing.
- **Silence is not a "no".** Twilio reports a silent timeout as `FinishedOnKey=""`. Sathi
  then asks again kindly. After a second silence it ends the call and the scheduler calls
  back later. Before this change, a silent timeout counted as "I did not do this".
- **9 #** reaches a person. The call task goes to the supervisor queue at high priority.
- **8 #** switches between Bangla and English and remembers the choice.

Customers can also say the amount. Sathi understands Bangla and Banglish number words,
including দেড়, আড়াই and সাড়ে ("tin hajar pach sho", "আড়াই হাজার", "3.5k").

A denial needs an explicit phrase such as "ami kori nai", "আমি তুলিনি" or "I did not". A bare
"na" or "no" usually means "I didn't understand", so it is treated as unclear and never as
a denial.

## Sathi Sahayak (customer assistant) and its guardrails

`POST /api/v1/assistant/chat` is available to customers only. The assistant answers in the
customer's language and handles these requests:

- balance and recent cash-outs, shown with neutral check states only;
- "the agent gave me less cash" and "I did not do this": the cash-out goes to the
  supervisor call queue at high priority;
- talk to a person;
- change the call language;
- how Sathi works, the secret help signal, and PIN safety.

How the assistant resists manipulation:

1. **Input guard.** Prompt injection (in English, Bangla and Banglish), PIN or OTP
   fishing, other people's IDs or phone numbers, relatives' accounts, and questions about
   internal flags or scores all get a fixed safety answer. Nothing is looked up for them.
2. **Actions only from the deterministic intent classifier.** The language model can never
   trigger an action.
3. **Facts limited to the signed-in customer**: their balance and last 5 transactions.
   Agent details, case status and scores are never loaded, so they cannot leak.
4. **Optional LLM rephrasing** (Gemini or GPT-4o, when a key is saved). An LLM reply is
   used only if it passes four checks:
   - redaction leaves it unchanged (no foreign ID, phone number or email);
   - every number in it comes from the customer's own facts;
   - it is in the same language as the customer's message;
   - it contains no injection or secret text.

   Otherwise the template reply is sent instead.
5. **Rate limit**: 20 messages per 5 minutes per customer.
6. **Redacted audit log** in `assistant_messages`.

Tests (`test_assistant.py`) cover all of the above, including a compromised LLM that tries
to invent a balance, leak another customer's ID or echo an injection.
