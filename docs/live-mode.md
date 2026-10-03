# Live mode: real calls, real-time risk, AI briefs and ecosystem intelligence

This document covers the production-shaped extension added on 3 October 2026. The
simulation console remains the default: everything below runs with no external account,
and each external service is switched on only by setting environment variables.

## Track coverage

| Track | Feature | Where |
|---|---|---|
| 07 Open Innovation | Scoped one-time cash-out mandate confirmed on a call to the customer's registered phone | `backend/app/voice/`, console "Live Mandate Simulator" |
| 01 Trust & Risk | Real-time mandate risk with rule trace and risk-based step-up; silent duress signal; AI investigation assistant | `backend/app/policy/risk.py`, `backend/app/copilot/investigator.py`, console "Review Queue" |
| 05 Merchant & Agent | 7-day agent cash-out demand forecast with P90 and an opening-cash recommendation | `backend/app/intelligence/liquidity.py`, console "Liquidity Forecast" |
| 04 Growth & Campaign | Uplift (T-learner) targeting for Sathi enrollment and a fixed-budget channel optimizer | `backend/app/intelligence/uplift.py`, console "Adoption Uplift" |

## 0. Main flow: confirm every cash-out afterwards (current console)

1. The agent gives the cash and records it on **Cash-out** (customer + amount). The ledger is
   debited (amount + assumed fee), a receipt SMS goes to the customer, and a check opens.
2. Sathi immediately calls the customer's registered phone (simulated phone, Twilio or the
   Bangladesh gateway). The Bangla prompt never says the amount. The customer types the cash
   they received and presses `#`.
3. Same amount → **Verified**. A different amount twice (one retry for typos), `#` alone
   ("I didn't do this"), or the secret help signal (`0` first) → **Suspicious**, with a
   plain-language AI recommendation and a case for the supervisor. The AI never says
   "fraud"; the supervisor decides (AI summary, decision, extra checks on the agent).
4. No answer → **No answer**; the supervisor can press **Call the customer again**.

Who sees what: agents see their cash-outs with a neutral "Confirmation done / waiting /
missed call"; customers see balance, history, the incoming call and SMS; only supervisors see
Verified / Suspicious (Transactions page, Dashboard, Cases to review).

API: `POST /api/v1/cashouts` (agent), `GET /api/v1/transactions` (agent/customer, neutral),
`GET /api/v1/transaction-checks[?status=]`, `GET /api/v1/transaction-checks/{id}`,
`POST /api/v1/transaction-checks/{id}/call` (supervisor). Migration 007 adds `txn_checks` and
lets `voice_calls` belong to a check. The earlier request → confirm → one-time-code flow
(sections 1–2) is still in the API and tested, but no longer shown in the console.

## 1. Verification call (Track 07)

Flow:

1. The agent requests a mandate. The response includes a risk band and the required
   verification strength.
2. The agent taps **Call customer to confirm**. The server, not the agent, looks up the
   customer's phone in `SATHI_VOICE_PHONE_BOOK` and places the call.
3. The customer hears a Bangla prompt (`bn-IN`, Google voice via Twilio). The prompt never
   says the amount. The customer types the amount and presses `#`. Pressing `#` alone
   means "I did not ask for this".
4. A match moves the mandate to `verified`. Only then can the agent issue the one-time
   terminal code. A mismatch re-prompts once (the existing two-attempt limit) and opens a
   review case.

**Silent duress.** At enrollment, the customer learns one rule: if someone is forcing you,
type the amount with a leading zero (for example `03000`). On the phone this sounds
exactly like a normal confirmation. The mandate is held, and an `urgent` `duress_signal`
case opens for an analyst. Agent and customer screens show only "not verified" for
duress, refusal and final mismatch alike. Every call outcome ends with the same Bangla
closing sentence, so a person standing next to the customer cannot learn the outcome.

**Simulated provider (default).** With `SATHI_VOICE_PROVIDER=simulated`, no real call is
placed. The customer console shows an incoming-call handset. Its answers go through the
same `VoiceService.handle_digits` code as Twilio webhooks.

### Enabling real calls with Twilio

1. Create a Twilio account and buy or use a trial voice number. On a trial account, verify
   each phone you will call (Twilio Console → Verified Caller IDs). Allow Bangladesh in
   Voice → Settings → Geo permissions.
2. Deploy the API on a public HTTPS URL (Render blueprint: `render.yaml`).
3. Set these API environment variables (Render dashboard → sathi-api → Environment):

| Variable | Value |
|---|---|
| `SATHI_VOICE_PROVIDER` | `twilio` |
| `SATHI_PUBLIC_API_URL` | Public API origin, for example `https://sathi-api.onrender.com` (no trailing slash) |
| `TWILIO_ACCOUNT_SID` | `AC…` from the Twilio console |
| `TWILIO_AUTH_TOKEN` | Auth token from the Twilio console (secret) |
| `TWILIO_FROM_NUMBER` | Your Twilio number in E.164 form, for example `+1…` |
| `SATHI_VOICE_PHONE_BOOK` | `{"U_777_000001":"+8801XXXXXXXXX"}`: the demo customer's real test phone |
| `SATHI_STEP_UP_ENFORCED` | `true` to block app-keypad confirmation for medium/high-risk mandates |

4. Redeploy. `GET /api/v1/voice/config` (any signed-in role) must report
   `"live_calls": true` and `"public_webhook_configured": true`.

Webhook security: each call gets a random URL token, stored only as SHA-256, and every
Twilio request must carry a valid `X-Twilio-Signature` over the exact public URL. Phone
numbers are never stored in the database; only a masked form such as `+880•••••••678`.

Free-tier Render services sleep after inactivity. Open `/health` a minute before a live
demo so the first webhook does not time out.

### Cheapest channel for Bangladesh

Research on 3 October 2026 (public pages only; prices are planning ASSUMPTIONS until quoted):

| Option | Approximate cost per verification | Interactive keypad? | Status in Sathi |
|---|---|---|---|
| Twilio Programmable Voice to BD mobile | $0.06/min ([Twilio BD pricing](https://www.twilio.com/en-us/voice/pricing/bd)), ≈ ৳5.5 for a 45 s call | Yes (TwiML `<Gather>`) | Implemented and tested with signed webhooks; works today |
| Local voice gateway with DTMF, e.g. [Infosoftbd Voice API](https://infosoftbd.com/voice-api-solutions-in-bangladesh/) | Not published; local voice broadcast tiers are ৳0.45–0.70 per call ([BulkSMSDhaka](https://bulksmsdhaka.com/), [Tense](https://www.tense.com.bd/voice-message)) | Advertised: DTMF capture to a webhook with Bearer auth | `bd_http_ivr` adapter implemented against a documented JSON contract; needs the vendor's field mapping |
| Local voice broadcast only (one-way) | ৳0.45–0.70 per call | No | Not usable for amount confirmation |
| Local SMS, [Alpha SMS](https://www.alpha.net.bd/SMS/api/) (sms.net.bd) | ≈ ৳0.25 per SMS | n/a | Implemented for receipts and missed-call notices |

Recommendation: start live demos on Twilio (works now). For a pilot, ask Infosoftbd (or any
BTRC-licensed IPTSP with programmable IVR) for DTMF pricing and map their API to the
`bd_http_ivr` contract below. That should cut the per-verification cost roughly 5–10×.

#### `bd_http_ivr` contract

Environment: `SATHI_VOICE_PROVIDER=bd_http_ivr`, `SATHI_BD_IVR_BASE_URL` (HTTPS),
`SATHI_BD_IVR_API_KEY`, `SATHI_BD_IVR_WEBHOOK_SECRET` (16+ characters),
`SATHI_BD_IVR_LANGUAGE` (default `bn-BD`), plus `SATHI_PUBLIC_API_URL` and
`SATHI_VOICE_PHONE_BOOK`.

1. Sathi → gateway: `POST {base}/calls` with `Authorization: Bearer <key>` and
   `{"to", "callback_url", "status_url", "language", "prompt": {"text"}, "gather":
   {"max_digits": 8, "finish_on_key": "#", "timeout_seconds": 12}, "client_ref"}`.
   Reply: `{"call_id": "..."}`.
2. Gateway → Sathi: `POST callback_url` with JSON `{"event": "answered"}`,
   `{"event": "digits", "digits": "3000"}` or `{"event": "status", "status": "no-answer"}`,
   signed with `X-Sathi-Signature: hex(HMAC-SHA256(secret, raw body))`.
3. Sathi replies `{"action": "gather" | "hangup", "say": "<Bangla text>", "language",
   "gather": {...}}`. The gateway plays the text with its Bangla TTS and continues.

### SMS notifications

`SATHI_SMS_PROVIDER=alpha` with `ALPHA_SMS_API_KEY` (and optional `ALPHA_SMS_SENDER_ID`)
sends real SMS through `https://api.sms.net.bd/sendsms`. Without them, messages go to a
simulated outbox that the customer console shows as an SMS inbox. Two messages exist,
both sent after the fact so they never reveal an amount before the customer states it:
a Bangla cash-out receipt after redemption, and a notice after an unanswered
verification call. Each is sent at most once per mandate. A failed SMS is recorded and
never affects the ledger.

## 2. Real-time risk and step-up (Track 01)

`MandateRiskEngine` reads ledger signals inside one short transaction when a mandate is
requested: the saved agent anomaly score, amount relative to the customer's 90-day median,
first agent-customer pair, agent velocity (customers in 30 minutes), agent review cases in
7 days, the customer's mismatches in 24 hours, near-full withdrawal within 24 hours of a
credit, night requests, and near-cap amounts. Weights are documented ASSUMPTIONS in
`risk.py`. The output is a 0–1 score, a band and a step-up level:

| Band | Step-up | Effect |
|---|---|---|
| low | `keypad_or_call` | App keypad or call |
| medium | `call_required` | Call to registered phone (enforced when `SATHI_STEP_UP_ENFORCED=true`) |
| high | `call_and_review` | Call, plus a `high_risk_request` analyst case |

If signals cannot be read, the engine fails toward `call_required`, never toward approval.
Risk never approves, denies or blocks a cash-out. The agent's API response omits the
signal trace, so requests cannot be tuned around the rules. Analysts see the full trace
in case evidence and AI briefs.

### Fraud operations

- **Command Center** (`GET /ops/overview`, analyst): mandates, confirmation rate,
  paid-out and held amounts, call outcomes, risk bands, open/urgent/overdue cases, agents
  with most cases, and a live audit feed. Refreshes every 10 seconds.
- **Prioritized queue** (`GET /ops/cases`): urgent (duress, 15 min), high (refusal,
  high-risk request: 60 min; cash gap: 4 h), normal (mismatch, lockout: 8 h). The response
  targets are pilot ASSUMPTIONS. Cases past their target are flagged.
- **Case timeline** (`GET /cases/{id}/timeline`): audit events, calls, SMS and decisions
  in order.
- **Agent watchlist** (`PUT/DELETE /watchlist/{agent_id}`, `GET /watchlist`): an analyst
  puts an agent on enhanced verification with a reason. The risk engine then never gives
  that agent's mandates the low band, so every mandate needs a call. It never blocks the
  agent. Every change is audited.

## 3. AI investigation assistant (Track 01)

`POST /api/v1/cases/{id}/brief` (analyst only) collects structured evidence (case,
mandate, risk trace, verification events, calls, agent case counts), flattens it into
numbered facts, and asks an LLM for a brief that answers: what happened, why it is risky,
and what to do next.

Provider chain: Gemini (`GEMINI_API_KEY`, default model `gemini-2.5-flash`), then OpenAI
(`OPENAI_API_KEY`, default `gpt-4o`), then a deterministic template. Each answer is
schema-validated. Every claim must cite existing fact IDs, and the next step must come from
a fixed list. Invalid answers are discarded and the next provider is tried. Fact values
are passed as data with an explicit instruction to ignore embedded instructions. The
console renders all text escaped. Briefs are stored in `case_briefs` with the evidence
hash and provider, and an audit row records each generation. A brief is never a decision.

## 4. Agent liquidity forecast (Track 05)

`scripts/train_intelligence.py` trains a direct multi-horizon LightGBM model (point and
P90 quantile) on agent × Dhaka-day cash-out totals from the synthetic ledger. Features use
only information available at the forecast origin. The final 14 origins are held out.

| Metric (time holdout, 29,400 agent-days) | Value |
|---|---|
| LightGBM WAPE | 0.90 |
| 7-day moving average WAPE | 1.35 |
| Same-day-last-week WAPE | 1.63 |
| P90 coverage (target 0.90) | 0.897 |
| LightGBM WAPE on an unseen agent population (test split) | 0.92 |

Daily agent demand is lumpy, so absolute errors stay high. The model mainly learns the
allowance-cycle day (`target_dom` carries 66% of gain). Agents see only their own forecast.
The demo agent, which has no history, gets a labelled medium-volume cohort forecast. A
surge alert fires when the expected (not P90) peak exceeds the agent's busiest day in the
last 35 days, which spans one 30-day allowance cycle: 47 of 300 agents at the current
origin. The recommended opening cash is the peak P90 rounded up to ৳500. Forecasts never
limit a customer's cash-out.

## 5. Uplift targeting for adoption (Track 04)

The same script simulates a randomized outreach experiment on the synthetic users (50%
treated). It injects a documented heterogeneous effect: assisted users who depend on
one agent are persuadable, digital users are "sure things", and disengaged independents
react slightly negatively. A T-learner (two LightGBM classifiers) estimates individual
uplift. On a 30% holdout:

| Policy | Qini | True extra enrollments, top 20% |
|---|---|---|
| Uplift model (T-learner) | 76.4 | 278.5 |
| Response model | 68.8 | 253.0 |
| Agent-dependence rule | 60.4 | 213.2 |
| Random | −8.0 | 101.7 |

Predicted uplift correlates 0.62 with the injected truth. The optimizer
(`POST /api/v1/campaigns/optimize`) solves a one-channel-per-customer knapsack over SMS
(৳0.5), IVR call (৳3) and agent visit (৳40). Costs and effect multipliers are
ASSUMPTIONS. It never contacts customers with non-positive predicted uplift. Expected
extra enrollments versus spending the same budget on response-model IVR calls:
278 vs 226 at ৳2,000, 623 vs 583 at ৳10,000, and 832 vs 537 at ৳50,000.

## Settings page (analyst)

**System → Settings** edits runtime options without a redeploy. A value set here overrides
the matching environment variable, which overrides the built-in default. Each field shows
its source. **Reset** removes the override. Every change writes a `settings_updated` or
`settings_reset` audit row with old and new values. Set `SATHI_SETTINGS_EDITABLE=false`
to make the page read-only on a deployment.

| Group | Options |
|---|---|
| Channels | Verification call provider (simulated / Twilio / Bangladesh IVR), SMS provider (simulated / Alpha). A real provider can be chosen only after its secrets and an https `SATHI_PUBLIC_API_URL` are set |
| Risk policy | Enforce call for medium/high risk; low and medium band upper bounds (low must stay below medium) |
| AI assistant | Provider order (Gemini first, GPT-4o first, template only); model ids |
| Case response targets | Urgent, high, cash-gap and normal targets in minutes |
| Cost assumptions | USD→BDT, Twilio $/min, Bangladesh IVR ৳/call, SMS ৳, average call length; the Command Center cost card uses them |

### Provider credentials on the Settings page

Twilio, the Bangladesh IVR gateway, Alpha SMS, Gemini, OpenAI, the public webhook URL and
the registered phone book can all be entered under **Settings → Provider credentials**.

- Values are encrypted at rest with `SATHI_SECRETS_KEY` (server env, 32+ characters;
  `make init-env` generates it, Render generates it from `render.yaml`). Keep it stable:
  changing it makes saved values unreadable until re-entered.
- Write-only: the page shows only the last 4 characters (phones masked). A saved value
  overrides the env variable of the same name; **Clear** falls back to the env.
- **Test connection** runs a free, read-only check (account, balance or model lookup).
  **Place test call** / **Send test SMS** cost money and are limited to 5 per hour.
- Every save, clear and test is written to the audit log without the value.
- Demo analyst PINs are public. On a public deployment, enter the credentials, then set
  `SATHI_SETTINGS_EDITABLE=false` so settings and credentials become read-only.

Production go-live order: save the credentials, press **Test connection** on each card,
place one test call and one test SMS to your own phone, pick the providers under
**Channels**, then check **Go-live readiness** shows every selected provider as ready.

Not editable on the page:

- **Ledger policy** in `data/config.yaml` (caps, fees, attempts, expiry): hash-locked to
  the verified model bundle.

Values are stored in `app_settings` (migration 005). API: `GET /api/v1/settings`,
`PUT /api/v1/settings` with `{"changes": {key: value}}`, `DELETE /api/v1/settings/{key}`.
All three require the analyst role.

### Go-live readiness panel

The Settings page renders a "Go-live readiness" section below the secrets and phone-book
panels. For each provider currently selected in Settings (Twilio, Bangladesh IVR, Alpha
SMS, Gemini, OpenAI) it shows which environment variables are set on the server, which
are still missing, and a one-line hint telling the operator exactly what to put in
`.env` before flipping the matching selector. The panel does not touch the network;
it is cheap enough to render on every page open.

The **Run live probe** button calls `GET /api/v1/settings/probe`, which runs the same
auth-only probes as `scripts/preflight.py` against each provider, in real time. Twilio
and Alpha probes use the providers' own magic numbers / test endpoints (no call placed,
no SMS sent); Gemini and OpenAI use a one-token handshake. The probe results land in
each provider's panel card with a "re-run" button for that single provider. The
panel is the analyst's single-page endpoint: the analyst's single view of what is
actually wired up before flipping a selector in production.

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | /settings/readiness | analyst | Env-var status per provider + selection summary; no network calls |
| GET | /settings/probe?only=<name>&timeout=<s> | analyst | In-process auth-only probe of one or all providers |

## Reproduce

```sh
PYTHONPATH=backend .venv/bin/python scripts/train_intelligence.py
```

The script writes `data/artifacts/intelligence/{liquidity,uplift,manifest}.json`. The
manifest records SHA-256 hashes, seed, dataset hashes and the git revision. The API
verifies the hashes on every request and returns 503 if any artifact was changed. No
model runs at request time.

## New API routes

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | /voice/config | any signed-in role | Which channel is live; never credentials or numbers |
| POST | /mandates/{id}/call | bound agent | Call the customer's registered phone |
| GET | /mandates/{id}/call | owning agent or customer, analyst | Latest call status (duress hidden except for analyst) |
| GET | /voice/incoming | customer_channel | Simulated handset: ringing calls |
| POST | /voice/calls/{id}/simulated-answer | owning customer_channel | Simulated keypad answer through the real digit logic |
| POST | /voice/calls/{id}/answer, /gather, /status | Twilio (signed webhook) | TwiML prompt, digits, call status |
| POST | /cases/{id}/brief | analyst, super_admin | Grounded AI case brief |
| POST | /voice/ivr/{id}/events | Bangladesh IVR gateway (HMAC-signed JSON) | answered / digits / status events |
| GET | /notifications | customer_channel (own), analyst | SMS outbox and delivery status |
| GET | /ops/overview | analyst, super_admin | Command Center metrics and live feed |
| GET | /ops/cases | analyst, super_admin, supervisor | Cases with priority and response-target status |
| GET | /cases/{id}/timeline | analyst, super_admin, supervisor | Ordered case events |
| GET, PUT, DELETE | /watchlist, /watchlist/{agent_id} | analyst, super_admin | Enhanced-verification watchlist |
| GET | /liquidity/overview | analyst, super_admin | Forecast metrics and agents needing extra cash |
| GET | /liquidity/agents/{id} | that agent, analyst, super_admin | Agent's own 7-day forecast |
| GET | /campaigns/uplift | analyst, super_admin | Experiment, Qini curves, drivers |
| POST | /campaigns/optimize | analyst, super_admin | Budget allocation plan |

`POST /mandates/request` now also returns `risk` (`score`, `band`, `step_up`,
`engine_version`). With `SATHI_STEP_UP_ENFORCED=true`, `POST /mandates/{id}/verify`
returns `403 STEP_UP_REQUIRED` unless the mandate's step-up is `keypad_or_call`.

### Roles

Three operator roles share the same UI surface. They are pure-widening splits —
the legacy `analyst` role still works exactly as before:

- **`analyst`** (default, e.g. `analyst_777 / 9012`) — every page, every decision.
  Backwards-compatible; all pre-refactor tests still pass.
- **`super_admin`** (e.g. `admin_777 / 7890`) — same surface as analyst **plus**
  the Settings page and the AI case brief endpoint. Day-to-day operator.
- **`supervisor`** (e.g. `supervisor_777 / 3456`) — **cases-only**. Read-only
  access to the case queue, the prioritized queue, and the per-case timeline.
  No Decide, no AI brief, no Settings, no watchlist edits, no campaign optimizer.

The Cases tab in the navigation is the only one supervisor can see. Every other
operator tab hides itself from supervisor. Both new roles are wired in
`data/config.yaml` under `auth.principals` and exposed on the demo login card.

## Go-live checklist (run before deploy)

The project ships a one-shot preflight script and a guarded live-test
module. Use them after filling in `.env`:

```sh
# 1. Probe every configured provider without exercising any application code.
make live-preflight

# 2. Run the live (real-network) provider test module. Skipped unless
#    SATHI_LIVE_TESTS=1 + the matching provider env vars are set.
SATHI_LIVE_TESTS=1 make live-tests

# 3. (Optional) Roundtrip the BD-IVR webhook contract end-to-end against a
#    local stand-in. Only useful until a real vendor confirms the contract.
docker compose --profile live up -d bd_ivr_standin
SATHI_LIVE_TESTS=1 SATHI_BD_IVR_API_KEY=... SATHI_BD_IVR_WEBHOOK_SECRET=... \
    PYTHONPATH=backend pytest backend/tests/test_live_providers.py -v -k bd_ivr
```

### Credentials

| Integration | Env vars (place in `.env`) | Probe target |
|---|---|---|
| Twilio voice | `SATHI_VOICE_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `SATHI_PUBLIC_API_URL` | `https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json` |
| Alpha SMS receipts | `SATHI_SMS_PROVIDER=alpha`, `ALPHA_SMS_API_KEY`, `ALPHA_SMS_SENDER_ID` | `https://api.sms.net.bd/sendsms` |
| Gemini case brief | `GEMINI_API_KEY`, `SATHI_GEMINI_MODEL=gemini-2.5-flash` | `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` |
| OpenAI case brief (fallback) | `OPENAI_API_KEY`, `SATHI_OPENAI_MODEL=gpt-4o` | `https://api.openai.com/v1/chat/completions` |
| Bangladesh IVR (vendor pending) | `SATHI_VOICE_PROVIDER=bd_http_ivr`, `SATHI_BD_IVR_BASE_URL`, `SATHI_BD_IVR_API_KEY`, `SATHI_BD_IVR_WEBHOOK_SECRET` (≥16 chars), `SATHI_BD_IVR_LANGUAGE=bn-BD` | `{base}/calls` + signed callback |

`scripts/preflight.py` probes each row with auth-only requests; it never
places a call or sends an SMS. `backend/tests/test_live_providers.py` is
the per-provider counterpart that hits the same wire formats from Python.

## Limits

- Twilio and the `bd_http_ivr` adapter are covered by request-shape, signature and
  end-to-end webhook tests. Twilio is now probed live against the real API
  with magic-number credentials (no real call placed). No Bangladesh vendor
  has confirmed the JSON contract yet — the local stand-in gateway at
  `scripts/bd_ivr_standin.py` roundtrips the webhook contract without a
  vendor.
- Alpha SMS is tested against its documented request and response format
  AND probed live against the real `sendsms` endpoint (no real SMS sent to
  a customer).
- The Gemini and OpenAI clients are probed live with a 1-token handshake
  when `SATHI_LIVE_TESTS=1`; the regular test suite uses stub clients so
  no LLM credits are consumed by CI.
- Liquidity and uplift results come from synthetic data with injected patterns. They
  show the method works, not real-world impact.
- Duress protection depends on the customer remembering the rule. Like all confirmation,
  it cannot prove physical cash delivery.
