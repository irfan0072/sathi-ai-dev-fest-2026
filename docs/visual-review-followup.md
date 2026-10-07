# Sathi: browser review after Claude's sprint

Reviewed 7 October 2026. Product code was not changed by this review.

## Runtime and coverage

The application was started at `http://127.0.0.1:13020`, with a separate synthetic review database and `SATHI_DEPLOYMENT_MODE=public_demo`. No existing project database or private `.env` credentials were used. Real voice/SMS/online AI were disabled. Existing generated data was loaded into this new database: 20,000 synthetic users and 300 agents, plus demo fixtures. This review is not a live-provider or production deployment validation.

All **26 unique navigation page IDs** were opened across the five roles. Both desktop (1366 × 900) and phone (390 × 844) layouts were inspected, including the 20 admin pages at phone width and in light mode. Dark-theme screens, role-specific pages, all five metrics tabs, customer reporting form, case summaries and follow-up panels were inspected. This is broad visual and representative workflow coverage, not an exhaustive test of every data row, every browser or every possible input/state combination.

| Area | Pages covered |
|---|---|
| Agent | Cash-out, own cash planning, How it works |
| Customer | My account, assistant/inbox/call controls, Send money, Scam alerts/report form |
| Supervisor | My desk, Call queue, independent follow-up detail, Cases/workbench, Scam watch, Workflow evidence |
| Super admin | Control center, Call management, Cases, All transactions, Scam watch, Customers, Agents, Test accounts, Supervisors, Audit log, Settings |
| Analytics | Fraud dashboard, Confirmations, Agent review ranking, Cash planning, Customers who need help, Invite planner, Workflow evidence, AI test results and its five tabs |
| Analyst | Separate Cases to review queue, case detail/timeline and clearance action |
| Shared | Sign-in/out, role switching, drawer, light/dark themes, How it works |

Screenshots and DOM-based observations are saved in:

`/Users/apple/.codex/visualizations/2026/10/07/01a11448-2fd7-75e0-a14e-66efd37d6c0a/sathi-review/`

`review-observations.json` records rendered content and responsive measurements. `light-contact-sheet.jpg` and `mobile-contact-sheet.jpg` provide overviews. Some sweep screenshots caught drawer/fade transitions; settled screenshots and measurements were used for findings. The incorrectly named `mobile-customer-account.jpg` captured the second desktop tab and is not evidence of phone sizing; use `customer-mobile-dark.jpg` instead.

## Working behavior verified

- All five published demo roles sign in and receive their own navigation. Role switching and sign-out work.
- A synthetic ৳500 cash-out followed by two ৳400 answers opens a case. The retry wording does not disclose an amount mismatch. The customer's final message is neutral.
- A ৳600 answer matching a ৳600 cash-out completes the check.
- A leading-zero answer to a ৳700 cash-out creates secret-help evidence and independent follow-up without revealing the outcome on the customer screen.
- A supervisor can claim and record an unresolved follow-up. An analyst's attempt to clear that case is rejected with `INDEPENDENT_CONTACT_REQUIRED`; the case stays open.
- The case-brief button returns a labeled deterministic summary in public-demo mode.
- Public-demo simulator management is refused by the API. Settings are visibly view-only.
- Live rankings, outreach, forecast, campaign simulation, workflow evidence and frozen metrics load once their normal background jobs finish.
- The measured phone-width pages have no document-level horizontal overflow. Wide tables use internal scrolling; that alone is not a responsive defect.

## Remaining findings, in priority order

### 1. Secret-help follow-up is not marked urgent

Reproduction: cash-out ৳700, customer presses `0700#`, then Supervisor → Call queue → Independent follow-up. The new task appears with **high**, not urgent, alongside the older mismatch. The detail confirms a secret help signal. `txn/service.py` adds urgent priority to case evidence but only promotes the call task to high, and `CallCenterService.on_resolved` also assigns high for suspicious checks. The dedicated follow-up queue sorts by the task priority, so urgency is lost there.

Fix task priority at the source and preserve it through resolution/retry/follow-up transitions. Test both the call queue and case queue. Keep staff-only urgency; do not change customer-visible output.

Evidence: `mobile-duress-priority.jpg`, `mobile-duress-detail.jpg`; `backend/app/txn/service.py`, `backend/app/callcenter/service.py`.

### 2. An unreachable customer's check falsely says “answered”

The first test transaction was not answered. After retries, the review database contained `(check_id=1, status='unreachable', outcome=None, attempts=0)`. The customer nevertheless saw **“Thank you, answered”**. `txn/router.py:_public` maps every state except pending/calling/no_answer to `done`, and customer copy interprets that as an answer.

Use honest neutral states for unreachable/manual-review and keep mismatch/duress outcomes concealed. Verify the same mapping in agent history. Never imply successful customer confirmation when none happened.

Evidence: `customer-mobile-dark.jpg`; `backend/app/txn/router.py`, customer history components/copy.

### 3. Exact money is rounded differently across screens

For the same ৳500 cash-out, agent/customer history shows the actual **৳7.5 fee**, but All transactions shows **৳8**. The shared `ops/kit.jsx:bdt` rounds every value with `Math.round`. This also affects balances and transaction details.

Use an exact transaction-money formatter that retains cents. Keep approximate compact formatting separate for aggregate dashboards and explicitly rounded cash-planning recommendations. The ledger itself was not shown to be wrong; the presentation is inconsistent.

Also check the ledger's “newest first” promise: `admin/router.py` sorts by transaction ID, while imported histories can have timestamps in a different order. Change the ordering/cursor consistently or label the intended ordering correctly.

Evidence: `admin-ledger.jpg`, `admin-audit.jpg`; `frontend/src/components/ops/kit.jsx`, `backend/app/admin/router.py`.

### 4. Critical warning is nearly unreadable in dark mode

The global synthetic/concept banner uses dark `text-warning-content` on a translucent dark warning background. It is nearly invisible at desktop and phone widths. Several agent-ranking badges wrap beyond their fixed badge height and overlap adjacent lines. The How it works step badge also clips/wraps. The light-theme public-demo status chip needs a contrast check.

Use theme-appropriate text/background pairs and verify actual settled rendering, including keyboard focus. Give risk labels sufficient width/height, or separate the score from the badge. Do not hide the synthetic disclosure to solve contrast.

Evidence: `agent-dark.jpg`, `customer-mobile-dark.jpg`, `agent-ranking.jpg`, `mobile-agent-review-ranking.jpg`, `light-how-it-works.jpg`.

### 5. Sparse-history forecast gives unjustified-looking advice

The demo agent had only very small recent cash-outs. Its cash-planning panel recommended approximately **৳29,000**, compared with a recorded peak of **৳500**, and described a peak as **1621.4×** a usual day of approximately **৳18**. It presents this as the agent's own pattern rather than identifying a cold-start or peer fallback. Background computation worked after correcting the review launch method; the issue is the meaning and confidence of the displayed advice.

Require sufficient observed history for individual advice, or show an explicitly qualified peer estimate. Avoid extreme ratio claims when the baseline is tiny. Do not just clip the recommendation to a convenient number or tune the model to this example.

Evidence: `agent-sparse-forecast.jpg`; `backend/app/live/intelligence.py`, intelligence/liquidity implementation and `LiquidityPage.jsx`.

### 6. Public-demo controls advertise actions that are disabled

The simulator still shows a clickable Start button; it returns “Settings are read-only on this deployment.” Test accounts still invite judges to create real customers and configure calls. Staff management still displays Create, Reset PIN and Deactivate controls. Backend protections are valuable, but the UI looks broken and invites unavailable actions.

Use deployment metadata consistently to disable/hide unavailable management controls and explain why. Preserve operative synthetic cash-out and case-review demonstration controls. Do not weaken API restrictions to make the buttons work. Customer/community forms and public-demo labels should distinguish actual supported simulation from partner-dependent features.

Evidence: `admin-control-center.jpg`, `admin-test-accounts.jpg`, `admin-staff.jpg`, `admin-settings.jpg`.

### 7. Case decision forms have unsafe defaults and inconsistent meaning

Supervisor case work defaults to **Problem confirmed** and pre-checks **Customer contacted**, despite this review case having no real independent contact. The analyst uses the ambiguous labels **Approve/Deny**, while operator workflows mean Cleared/Problem confirmed. Its timeline still says **“AI marked it suspicious.”** The independent-follow-up status is not prominently shown before the analyst attempts clearance and receives an error.

Default the contact flag to false and require deliberate choice of outcome. Align labels and show the independent-contact requirement/status before submission. Preserve the existing server clearance gate. Calling a task “Resolved” while follow-up is required is technically a separate lifecycle, but the UI should explicitly distinguish “automated call finished” from “case resolved.”

Evidence: `supervisor-case-detail.jpg`, `analyst-case-detail.jpg`, `analyst-clearance-blocked.jpg`; `CaseWorkbench.jsx`, `ReviewQueue.jsx`, `backend/app/ops/router.py`.

### 8. Several judge-facing claims remain stale or misleading

- How it works says secret help **“the cash is stopped”**, although its own steps say money already left the account. This is false for the post-cash-out flow.
- It hardcodes **5M customers / 20k agents**, while this run actually has approximately **20k / 301**. Historical scale tests should be labeled separately from current runtime counts.
- It asserts an unvalidated **30–50% village cash-out** estimate. Remove or clearly source/qualify it; do not present it as established problem evidence.
- Invite planner describes **“a past test”** in which customers received invitations, while the outcomes were generated. The synthetic causal assumption should appear at the point of claim, not only in an assumptions paragraph below.
- Outreach explanation says **every active customer**, while the page's actual scored pool is capped at 6,000. Its lower coverage card is more honest than its guide.
- The metrics page's money-saving summary does not prominently distinguish a hypothetical perfect-compliance mandate counterfactual from the primary detection-only workflow.
- Call-center copy labels deterministic transcript/keypad handling **AI calls/AI cannot confirm**. The timeline repeats “AI marked it suspicious.”
- The community-report form promises nobody, including staff, can know who posted. A keyed/pseudonymous record is not an unconditional anonymity guarantee.

The expanded benchmark is only mentioned as a plain repository path. Its new held-out counts and failure results are not available as an actual judge-facing table/tab in the console. Preserve old results, but give judges a clear versioned extended-evidence view with final-cohort denominators, unchanged-fee failures and the undeployed candidate label.

Evidence: architecture, metrics, outreach, invite-planner and case screenshots; relevant page components and `ops/router.py`. The old report also remains stale per Claude's own completion note.

### 9. Advertised scam-demo numbers do not work in a normal small setup

The Send money page advertises `01900000500` as being in community alerts. Checking it returned **“No reports found … No upay account uses this number”**, styled green. Scam alerts and Scam watch were empty. A direct call to the existing fixture initializer returned `{'seeded': False, 'reason': 'scale population not loaded'}`.

The normal documented synthetic-data setup should support a small independent scam demonstration without loading five million users. Seed clearly synthetic fixtures idempotently into demo mode, or derive/hide demo instructions based on actual fixture availability. Unknown/missing coverage must not look like an affirmative safety signal. Do not generate accusations against actual people or real phone accounts.

Evidence: send-money screenshot/observations; `backend/app/scam/seed.py`, `ScamProtection.jsx`.

## Verification

Independent frontend run: **67 passed**; ESLint and production build passed. Ruff and structure checks passed. A fresh database-backed full backend run was started; the completed count is appended below. This run uses PostgreSQL 18.4, not the declared PostgreSQL 16 target. Real-provider tests remain outside this review.

The initial review API launcher used stdin, which cannot be re-imported by Python's spawned model workers. It was replaced with a file-based launcher, and model pages loaded. That temporary launcher problem is not attributed to Claude's application changes.

## Recommended finish

Fix priority/state/money and the misleading workflow claims first. Then repair contrast/badges, align read-only UI and default scam fixtures, and expose extended benchmark evidence. Keep the sprint bounded: no new model training, real pilot claims, provider rollout or major redesign. Recheck the same browser reproductions after fixes.

## Completed independent verification

Backend: **762 passed, 8 skipped, 124 warnings in 120.15 seconds**, using disposable schemas on PostgreSQL 18.4. Frontend: **67 passed**. Ruff, ESLint, structure validation and production build passed. The eight skips are live-provider tests. No real-provider operations, production changes or application fixes were made by this review. These passing tests do not cover the demonstrated remaining browser findings.
