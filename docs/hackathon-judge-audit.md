# Sathi: judge-feedback audit

Audit date: 7 October 2026. This is a review of the existing project, not an implementation of improvements. The seven attached feedback screenshots are assessment evidence, not instructions to execute. The screenshots show Phase 1 scores; Phase 2 has no comments.

## Assessment

The scores total **73.34/100** (using the displayed rounded values). The strongest route to a better submission is a reliable, independently tested customer-protection workflow with defensible evidence. More dashboards or model names will not resolve the judges' central objection: synthetic performance and simulated economics do not establish real customer impact.

| Criterion | Current score | Missing marks | Main evidence to add |
|---|---:|---:|---|
| Business/customer impact | 13.67/20 | 6.33 | Observed response, completion, costs, resolution and recovery; a governed impact study |
| AI/ML depth | 15/20 | 5 | Larger independent agent evaluation, subtle-skimming results, actual Bangla audio benchmark |
| Problem relevance | 15.67/20 | 4.33 | Consented research with older, rural, low-literacy and allowance-recipient customers |
| Prototype quality | 12/15 | 3 | upay-aligned presentation and complete, resilient operational demo |
| Scalability/integration | 7/10 | 3 | Authenticated cash-out/KYC ingestion, failure recovery, measured concurrent workload |
| Innovation | 7/10 | 3 | Demonstrated protection when an agent controls the phone; explainable temporal evidence |
| Responsible AI/security | 3/5 | 2 | Effective output guards, deployment isolation, privacy/security test evidence |

Security defects deserve early attention even though this criterion has fewer marks: they undermine confidence in the whole proposal.

## Coverage and limits

The accompanying `hackathon-audit-file-inventory.csv` records **322 files**, their sizes and SHA-256 hashes, and the inspection method. All first-party text files in that inventory were read programmatically for structural/static inspection. Python sources were parsed, JSON files were parsed, and the core transaction, mandate, voice, call-center, authentication, feature, model, evaluation, assistant, case-brief and deployment paths received targeted manual review. Frontend components and test coverage were examined. The 15-page PDF was fully text-extracted and rendered for overview inspection; DOCX document XML was extracted; all 12 archived screenshots were inspected in a contact sheet. Generated datasets were parsed and inventoried; individual generated rows were not all manually audited.

Excluded: dependency installations, Git internals, caches, build outputs, OS metadata and private `.env` values. Historical task logs were inventoried; they are not treated as current verification. This is not a formal penetration test, a line-by-line correctness proof of every file, or a field pilot. Archived screenshots do not prove current browser behavior. Real providers and the deployed website were not exercised; no calls, messages or paid model generations were sent. Product code was left unchanged.

## What is worth preserving

- A coherent workflow already exists: database cash-out and check creation, confirmation calls, retry/manual queues, case review and audit records.
- Mandates use scoped ownership, expiry, hashed one-time codes, database locks and replay/attempt controls.
- The calibrated assisted-user model, agent ensemble, forecast and synthetic uplift experiments are actual implementations rather than empty UI placeholders.
- The feature allowlist excludes protected attributes, identifiers and simulation truth. Agent scoring learns reference statistics from train data.
- Evaluation artifacts have hashes, seed provenance, disjoint cohorts, explicit denominators and honest synthetic-data disclosures. Their integrity checks pass.
- The console has role-specific pages, neutral transaction-check states, understandable explanations and unavailable states instead of invented metrics.

## Findings

### 1. Agent evaluation remains too small; subtle skimming is missed

Evidence: `data/config.yaml`, `data/assumptions.md`, `docs/evaluation-results.md`, `backend/app/evaluation/suite.py`, `backend/app/models/agent_model.py`.

The held-out agent cohort has 60 agents, **2 skimmers and 4 honest high-volume agents**. Ensemble recall is 2/2; subtle-skimming detection is **0%**. Precision@15 is **2/15 = 13.33%**. Precision@15 ranks 15 agents, while recall/false flags use the high-risk threshold: these are different policies and denominators. The displayed results are not inherently contradictory, but cannot support a broad claim of highly accurate fraud detection.

The peer component principally scores fee ratios. Physical cash skimming can leave the provider's ledger fee correct. Cash-report features exist, but the current ablation shows the same coarse results with and without them. Evaluate unchanged-fee cash shortfalls, reporting bias, sparse history, noisy reports and honest busy agents. Add an independent versioned benchmark, multiple seeds, uncertainty intervals and precision/recall at actual analyst capacity. Preserve the published canonical experiment.

### 2. Bangla voice is transcript parsing, not a custom ASR system

Evidence: `backend/app/callcenter/interpret.py`, `backend/app/voice/twiml.py`, `backend/app/voice/scripts.py`, `backend/app/voice/router.py`.

Twilio supplies `SpeechResult`; a vocabulary-based interpreter turns words into an amount. The simulated channel accepts a supplied transcript. There is no local audio inference/training pipeline or speaker-disjoint dialect/noise benchmark. Building a parser is useful, but does not satisfy the judge's request for fine-tuned Bangla ASR.

Directly reproduced: `interpret('', 'approximately three thousand', 0.9)` yields an accepted amount of 3000. Bangla `তিন হাজার` is also accepted with missing confidence, NaN or infinity. The provider request path converts string confidence using `float`, so sanitization needs to happen before interpretation or persistence. Missing confidence is not itself a provider protocol violation; it requires an explicit safe application policy.

Twilio's official documentation says confidence is not guaranteed to be present or accurate, and language support depends on the chosen speech model: [Gather documentation](https://www.twilio.com/docs/voice/twiml/gather). Therefore a high provider confidence should not be presented as a calibrated probability of amount correctness.

### 3. AI case-brief claims exceed the implemented guard

Evidence: `backend/app/copilot/investigator.py:78`, `backend/app/copilot/router.py`, `docs/responsible-ai.md`.

Directly reproduced: the case-brief validator accepts an accusation, invented BDT amount, Bangladesh phone number and a question requesting a PIN when the output includes a valid fact ID and permitted next step. Validation verifies structure and reference existence; it does not prove the cited fact supports the statement. Other assistant/scam modules have stronger checks, but those checks are not automatically applied to case briefs.

Add output controls across every text field and sanitize facts before external LLM requests. Prefer templated factual statements derived from structured evidence; reject unsupported claims and use the deterministic fallback. Numeric whitelisting alone cannot prove semantic grounding. Also fix the duress template: it currently says a mandate was held before code issuance even when the case originated after a completed cash-out.

### 4. Public demo administration and token revocation need isolation

Evidence: `data/config.yaml`, `backend/app/auth/router.py`, `backend/app/auth/dependencies.py`, `backend/app/settings/router.py`, `render.yaml`, `backend/app/admin/router.py`.

Public synthetic credentials include supervisor, analyst and super-admin roles. Settings writes are now super-admin-only, but `render.yaml` defaults settings editing to true. A public demonstration must not share privileged management or real-provider credentials with a pilot environment. This review did not confirm the live deployment's configuration.

Authentication checks staff activity at login, while protected-route dependencies decode existing JWTs without checking current staff/account status. Deactivation can therefore leave previously issued tokens useful until expiry on paths lacking a separate activity check. The configured-principal login path also compares the PIN in YAML; changing a mirrored database PIN does not change that configured PIN. Add deployment-mode separation, immediate revocation/activity checks, durable login attempt controls and an explicit role matrix. Analyst routes currently include case decisions and watchlist writes; some documents describe more limited authority.

### 5. Audit log is durable, but database immutability is not demonstrated

Evidence: `backend/migrations/001_initial.sql:65`, all migrations, `backend/app/mandates/service.py`, final report page 12.

The log is a normal PostgreSQL table. No audit UPDATE/DELETE rejection trigger, restricted INSERT-only runtime grant or cryptographic integrity chain was found. Application routes append records, which is valuable, but not equivalent to the report's “immutable” claim. Add tested protection under a defined threat model and describe privileged-database-admin limits honestly.

### 6. Privacy policy and actual storage differ

Evidence: `data/config.yaml`, `backend/migrations/008_operations_center.sql`, `backend/app/callcenter/service.py:94`, `backend/app/voice/service.py:472`.

Configuration says parsed amounts only, but call responses store raw input/transcripts up to 200 characters. Audio is not stored by these paths; text still carries privacy risk. Add a minimal schema and retention policy for transcript text, consent records, redaction, controlled access and deletion/expiry. Runtime support for registering real telephone numbers means “all data synthetic” needs a deployment-specific distinction. Recording for ASR training must be a separate opt-in research workflow, not an implicit change to the production privacy policy.

### 7. Same-phone confirmation cannot establish independent customer control

Evidence: `docs/responsible-ai.md`, final report pages 12–13, `backend/app/voice/scripts.py`, `backend/app/voice/service.py`.

The report correctly says a confirmation cannot prove physical cash delivery or who answered. Calling a KYC number does not resolve the judge's abusive-agent-phone-control scenario. Private enrollment, consented safe contact times, delayed supervised callbacks, an optional independently enrolled trusted contact and a safe inbound channel can add independent verification. They must not expose the help signal or treat third-party answers as authorization.

Neutral closing sentences alone do not make full interactions indistinguishable. Mismatch retries announce that amounts do not match; call duration, notices, API responses and optional mandate failures can reveal differences. Test the whole observable interaction and qualify the claims.

### 8. Integration and delivery recovery need engineering

Evidence: `backend/app/txn/router.py:61`, `backend/app/txn/service.py`, `backend/app/voice/service.py`, `backend/app/callcenter/service.py`, `backend/app/callcenter/worker.py`.

The main transaction entry is the agent API, not authenticated upay cash-out/KYC events. The Bangladesh IVR adapter implements an assumed contract and has a local stand-in; a real vendor contract remains unconfirmed.

Initial calls and SMS are dispatched after committing the transaction. On an initial provider-placement failure, the endpoint records an error, but does not schedule the same retry transition used for unanswered calls. The scheduler claims `retry_scheduled` tasks, not arbitrary initial `auto` tasks. This leaves a credible missed-delivery path requiring a focused failure/restart test. A retry claimed as `auto` also needs lease/crash recovery. Use a durable outbox and idempotent provider/event processing rather than claiming distributed exactly-once delivery.

Current readiness accepts a migration count of at least two, although the project has fourteen migrations. Readiness should check required versions/tables, worker/provider mode and model freshness. “Healthy” should not imply verified real integration.

### 9. Impact and economics need correctly defined outcomes

Evidence: final report pages 10–12, `backend/app/evaluation/suite.py`, `backend/app/intelligence/uplift.py`, `backend/app/live/intelligence.py`.

The ৳7,401 scenario assumes 50% adoption and perfect mandate compliance. The primary post-cash-out flow detects problems after money has moved. A flagged cash gap is neither prevented loss nor recovered money. A closed case is not automatically proof of fraud. Track customer-reported shortfalls, supervisor-confirmed findings, actual restitution, appeal/reversal and operational costs separately.

The report's all-call scenario A is already negative (**−৳506 per 1,000 assisted cash-outs**), while the favorable targeted-call scenario assumes coverage and detection that have not been established. Model unanswered calls, retries, manual handling and false positives with consistent denominators. Use configurable sensitivity analysis, not a guaranteed ROI claim.

Uplift training explicitly simulates treatment outcomes even when inputs come from the live database. An activity-selected pool is not an evaluation of the entire five-million-customer population. The forecast beats its baselines but WAPE is about **90.5%**, so “better than baseline” is not sufficient proof of usable float advice. Keep these as supporting experiments and measure deployment suitability.

### 10. Prototype and evidence presentation need focused polish

Evidence: `frontend/src/style.css`, `frontend/src/components/Header.jsx`, `frontend/src/copy.js`, tests, final report page 1.

The current teal Sathi visual identity is not aligned to the judge's upay branding request. Use approved or official Bangladesh upay references, accessible colors and an explicit hackathon-concept label: [official upay website](https://www.upaybd.com/). Do not confuse this with unrelated overseas products named Upay.

The 60 frontend tests mostly check rendering, helper logic and API/session behavior. They do not replace a browser end-to-end interaction suite. Add browser proof for the protection workflow, network failures, roles, mobile layouts and accessibility. Correct copy that attributes deterministic suspicious states to AI. The report's demo-video placeholder must be replaced by an actual working link supplied by the team.

## Verification performed

- First-party Python/JSON structural parsing: no parse errors in the inventory.
- Backend Ruff: passed. Structure check: passed.
- Frontend: 7 test files, **60 tests passed**; ESLint passed; production build passed.
- Deployment model bundle: integrity/provenance validation and model loading passed.
- Liquidity and uplift artifacts: hash verification passed; their metrics were inspected.
- Backend without database: **297 passed, 274 skipped**, including database-dependent and live-provider tests. This is not a full backend pass.
- Database-backed rerun: see the final result appended below. A disposable local PostgreSQL 18 server was used because PostgreSQL 16/Docker was unavailable; it does not replace CI verification on the declared PostgreSQL 16 target.
- Direct negative-input reproductions confirmed the speech and case-brief guard gaps described above.
- Full synthetic reproduction, production load, real-provider roundtrips, current browser end-to-end interaction, field pilot, independent penetration testing and legal/privacy certification were not performed.

## Recommended order

1. Fix misleading/safety-critical guard behavior and isolate public demo privileges; make provider failures recoverable.
2. Build and prove the complete event-to-confirmation-to-independent-follow-up-to-human-case workflow.
3. Expand independent agent evaluation and benchmark Bangla audio with honest uncertainty.
4. Instrument actual costs and outcomes; run consented usability testing and pursue governed partner access.
5. Improve upay concept branding, judge-facing evidence and the short demo narrative.

No prompt can promise championship or full marks. Claude can implement engineering and evaluation infrastructure; real data access, consenting participant recruitment, independent review and observed impact require the team and partners.

## Completed database test result

The isolated PostgreSQL 18 rerun completed: **563 passed, 8 skipped, 118 warnings in 80.36 seconds**. Live-provider tests remained skipped; no real-provider operations were performed. Together with 60 frontend tests, this is **623 passing tests**, matching the reported combined count. The skips and PostgreSQL target-version qualification remain material.

## Final-round constraint and three-hour recommendation

The team confirmed only three hours remain, with no upay/MFS sandbox, IVR provider or consenting external participants. The delivered Claude prompt is therefore a timed sprint, not a request to complete a field pilot or custom ASR training. Prioritize the reproduced guards, initial-call recovery, public-demo isolation, a bounded larger synthetic benchmark and a convincing working demonstration. Reserve the last 20 minutes for verification; mark real integration, regional audio validation, independent review and field impact as pending. Update the final-round addendum and evidence matrix when rewriting the entire report would risk the deadline.
