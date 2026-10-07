# Final-round sprint status (7 October 2026)

Three-hour sprint for Team Runtime Terrors. Hard constraints: no upay/MFS sandbox, no IVR provider
access, no consenting external participants. Nothing was called, texted, deployed, published or
purchased. Everything executable is local and synthetic. Existing work and the frozen evaluation
artifacts were preserved (`data/config.yaml`, `data/generated/**`, `data/artifacts/**` are
untouched; the saved deployment bundle still verifies).

## Elapsed-time checkpoints (machine clock, UTC)

| Checkpoint | Time | State |
|---|---|---|
| Start (minute 0) | 03:07:50 | Baseline: backend 563 passed / 8 skipped (PostgreSQL 18.4, disposable), frontend 60 passed |
| Safety fixes in and tested | ~03:25 | Case-brief guard, speech validation, call-failure recovery, public-demo isolation |
| Extended benchmark dev phase | 03:31-03:35 | 3 x 3,000 agents, candidate decided on validation only |
| Extended benchmark final phase | started 03:36 | Scored once (see `docs/evaluation-agent-v2.md`) |
| Scenario, evidence, economics, UI | ~03:35-03:50 | See below |
| Extended benchmark final phase done | 03:56:42 | 3 replications, 20 min each on a memory-constrained laptop |
| Full verification | 04:10-04:14 | Results below |
| Feature freeze | 04:14 (minute ~66) | Scope was complete; the minute-160 limit was not needed |

Optional items skipped on purpose: authenticated cash-out/KYC event simulator (contract note only,
in `docs/api-contracts.md`), a pretrained audio adapter, durable login-attempt limiter, upay brand
tokens (no approved asset kit; the public site exposes no palette), enrolled safe-contact
preference (no enrollment store exists, so only the registered-number and in-person channels are
modelled).

## What can be proven without partners

- **Implemented, locally tested:** the guards, the parser rules, the recovery, the follow-up queue,
  the deployment-mode isolation, the evidence export and the economics model.
- **Synthetic evidence:** the extended agent benchmark and the workflow evidence. Both come from our
  own simulator and a simulated provider. Neither is field impact.
- **Not proven, not claimed:** a real pilot, an upay integration, an independent penetration
  review, custom Bangla ASR training, real answer rates, real cost, recovered or prevented funds.

## What changed

See `docs/judge-feedback-traceability.md` for the request-to-evidence map. Summary:

1. **Case brief guard** (`backend/app/copilot/guard.py`, `investigator.py`). Reproduced: a brief with
   an invented amount, an accusation, a phone number and a PIN question passed because it cited an
   existing fact ID. Now every text field is guarded, an external model sees only a minimised fact
   allowlist, failing text falls back to a deterministic brief, the response states the mode, and
   the duress template no longer says a mandate was held after a completed cash-out.
2. **Speech validation** (`callcenter/interpret.py`, `voice/service.py`, `voice/router.py`).
   Reproduced: approximate, NaN, infinite and missing-confidence speech became an exact amount;
   "300 500" became 300,500 and "three thousand five thousand" became 8,000. Fixed; the safe policy
   for a missing confidence is "unclear, ask for the keypad".
3. **Initial call failure** (`voice/service.py`, `callcenter/service.py`, `worker.py`). Reproduced: a
   committed check stayed `auto` forever after a placement failure, and the worker's retry-failure
   path never used up its budget. Now bounded retries, manual queue (`provider_failure`), no
   duplicate call when acceptance is uncertain, crash-lease recovery.
4. **Public demo isolation** (`deployment.py`, settings/admin/auth). `SATHI_DEPLOYMENT_MODE`,
   read-only management, pinned simulated providers, staff-token deactivation, `render.yaml`.
5. **Audit and privacy.** Append-only audit triggers (migration 015); transcript redaction and
   retention purge; honest wording ("durable, append-only audit trail").
6. **Independent follow-up queue** (migration 015, call-center routes, case-clearance gate, UI).
7. **Extended agent benchmark** (`backend/app/evaluation/agent_benchmark.py`,
   `scripts/agent_benchmark_v2.py`, `data/benchmarks/agent_v2/`, `docs/evaluation-agent-v2.md`).
8. **Reproducible workflow** (`backend/app/ops/demo_scenario.py`, `scripts/demo_scenario.py`,
   `docs/evidence/workflow-evidence.json`) and **evidence/economics** (`ops/workflow_evidence.py`,
   `ops/economics.py`, `scripts/economics.py`, `docs/economics-sensitivity.md`).
9. **Console:** concept and deployment labels, honest AI wording, follow-up panel, workflow
   evidence page, case-brief mode label.
10. **Documents:** README, responsible-AI, API contracts, deploy guide, Bangla ASR spec, partner
    request, demo script, traceability.

## Remaining external dependencies

| Dependency | Needed for |
|---|---|
| upay/MFS sandbox and a governed, signed cash-out/KYC event feed | Real event ingestion; replaces the agent-API-only entry |
| A Bangladesh IVR provider contract (Bangla prompts, DTMF, signed webhooks) | Real answer, drop-off and cost numbers |
| Consenting participants (older, rural, low-literacy, allowance recipients, agents) | Usability evidence |
| Consented, speaker-disjoint audio and training compute | Any claim about Bangla ASR |
| Supervised in-person follow-up and a supported intervention (hold, reversal, restitution) | Independent contact in practice; any prevention or recovery claim |
| Independent security and privacy review, consent records, deletion process | Any security or privacy certification |
| The team: demo video, link, final report text | Submission |

## Stale claims in the source report (not edited: no reliable authoring workflow was used)

`docs/report/Sathi_Final_Report.docx` and `.pdf` still contain claims this sprint changes. Replace
them with the addendum wording before submission:

- "immutable audit log" -> "durable, append-only audit trail (database triggers; a database owner can
  still alter it; no hash chain)";
- the scenario A/B/C economics (-506 / +740 / +475) assume 50% of incidents are prevented; the call
  runs after the cash-out, so prevention needs a separate intervention. Use
  `docs/economics-sensitivity.md`;
- agent detection on 2 held-out skimmers: add the extended benchmark and keep the subtle-skimming 0%;
- "parsed amounts only": transcript text (redacted, capped, 30-day retention) is stored;
- Bangla voice: "provider transcript plus a word parser", not a custom or fine-tuned ASR model;
- demo-video link placeholder: the team must insert a real link;
- "AI flags": fixed rules flag; AI ranks cases for review; scores are review scores, not fraud
  probabilities.


## Exact verification results (final run, 7 October 2026)

| Check | Result |
|---|---|
| Backend tests, disposable local **PostgreSQL 18.4** (Homebrew, not the declared PostgreSQL 16 CI target; Docker was not running) | **762 passed, 8 skipped, 0 failed** in 106 s. Baseline was 563 passed / 8 skipped; 199 tests were added. All 8 skips are live-provider tests (`SATHI_LIVE_TESTS=1` not set): this is **not** a full pass of the live-provider tests |
| Frontend tests | **67 passed** (baseline 60), 8 files. Server-render tests, not end-to-end proof |
| Ruff (`backend`, `scripts`), structure check, ESLint, production build | All pass |
| Browser smoke (`scripts/browser_smoke.py --workflow`, Playwright/Chromium, desktop 1366 px and phone 390 px, real UI against the real API in `public_demo` mode) | All checks passed: labels, sign-in, call queue, follow-up tab, workflow evidence page, no horizontal overflow, no page errors, agent cash-out screen stays neutral, customer keypad answers, supervisor sees "Independent contact needed" |
| Frozen deployment bundle (`verify_artifacts`: hashes and current config) | Verifies |
| Frozen paths `data/config.yaml`, `data/generated/**`, `data/artifacts/**` | Unchanged (`git status` empty) |
| Extended benchmark archive (`--phase verify`) | Intact |
| Synthetic scenario (`scripts/demo_scenario.py`) | Passes; 11 call attempts, 6 answered, 5 clear outcomes, 1 unclear, 4 could not be placed; 2 cases (1 confirmed, 1 escalated, 0 cleared); `docs/evidence/workflow-evidence.json` |
| Real-provider tests, real calls/SMS, deployment, paid model use | **Not run** (no access, no authorization) |
| PostgreSQL 16 in CI | **Not verified.** Exact tested version above |

## Synthetic evidence, not real validation: how each result must be described

- Extended agent benchmark (`docs/evaluation-agent-v2.md`): final cohorts 3,600 agents, 120 skimmers,
  3,480 honest, 240 honest high-volume. Moderate skimming: deployed ensemble 120/120 flagged, 0/3,480
  honest false flags, rule baseline 0/120. **Subtle skimming: 0/120 flagged at the fixed 0.8 threshold.**
  Unchanged-fee moderate shortfall: ensemble 0/120; the development-selected candidate (not deployed)
  119/120; unchanged-fee subtle shortfall 0/120 for every method. The simulator gives honest agents zero
  fee noise, so moderate skimming is an easy task there.
- Workflow evidence: events from a simulated provider and synthetic customers. It shows the loop
  works and gives numerators and denominators. It is not field impact.
- Economics: assumptions only. With failed attempts and case follow-up modelled, a detection-only
  all-call workflow costs about ৳5,390 per 1,000 cash-outs; with no separate intervention the net is
  negative. The report's scenarios reproduce exactly (-506 / +740 / +475) and rely on a 50%
  prevention assumption the post-cash-out call does not provide.

## Criterion-by-criterion (what changed; no score is predicted)

| Criterion | Improved by | Still missing |
|---|---|---|
| Problem relevance | Independent follow-up for the agent-holds-the-phone case; partner request with usability tasks | Consenting older, rural, low-literacy participants |
| AI/ML depth | 3,600-agent synthetic benchmark with protocol, dev/final split, intervals, threshold and budget policies; honest 0% for subtle skimming; a shortfall candidate evaluated on dev only | Real labels; honest-agent noise; audio benchmark for Bangla |
| Responsible AI/security | Case-brief and speech guards, public-demo isolation, staff token revocation, append-only audit, transcript redaction and retention | Independent review, consent records, deletion process, durable login limiter |
| Scalability/integration | Failure recovery with bounded retries and crash lease; readiness requires every migration | Real event feed, IVR contract, load measurement |
| Innovation | Independent-contact gate on clearing a case; uncertain stays open | The supervised in-person contact itself |
| Prototype quality | Repeatable scenario, evidence page, browser-smoke-tested UI, labels | upay brand assets |
| Business/customer impact | Reproducible, configurable economics with the negative cases and an evidence export with denominators | Real pilot data, invoices, a supported intervention |
