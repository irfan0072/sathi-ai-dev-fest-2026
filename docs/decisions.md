# Decisions and open questions

## Start gate

Human-confirmed T+0: **1 October 2026, 10:00 AM, Asia/Dhaka (UTC+06:00)**. Confirmation received on 2 October 2026 at approximately 11:12 AM Asia/Dhaka. The year is resolved from the current event/session context.

Human confirmation: “yes T+0 been announced 1 OCtober 10 AM. today is october 2 11:12 am and time zone is Dhaka”.

The start gate is satisfied. Later phases are permitted by this gate; the human authorized project work on 2 October 2026 by instructing Codex to run `agy` and start working. The `agy --print` probe passed.

## Pending human decisions

No architecture, schema, API, evaluation-plan or configuration changes have been adopted.

1. Resolve evaluation-only region versus region-based agent peer groups.
2. Clarify requested mandate code/expiry storage, authenticated agent code delivery, and lockout/daily-limit persistence.
3. Specify missing cash-gap/lockout parameters and null fee/cap assumptions before dependent work.
4. Validation setup resolved below; implementation must use the approved config.

## Resolved implementer selection

The human supplied the `agy` alias and authorized project work. `/Users/apple/.local/bin/agy` is available; read-only print mode and interactive implementation were verified. See `agent-workflow.md` for command permissions and invocation details.

## 2026-10-02T11:53:35+06:00 — GitHub remote authorized

The human supplied https://github.com/irfan0072/sathi-ai-dev-fest-2026.git and explicitly instructed Codex to use it and continue work. Remote inspection returned no refs. Local existing history is preserved on main; no history reset or force push is authorized or used. Regular pushes to this remote are authorized.

## Phase 1 scenario responses

- Fee/cap proposal was not adopted: human chose to keep settings unset and will supply different simulation values.
- Official fee rate, mandate cap and daily limit remain null in config; generator/policy work needing them remains gated.
- Human approved validation seed 4242 and disjoint 60/20/20 train/validation/test agent allocation. Existing train/test seeds 42 and 2026 remain. Config, assumptions and evaluation plan updated accordingly.
- Human responses recorded before config/evaluation-plan edits. No fee/cap values were assumed.

Confirmation recorded at 2026-10-02T12:19:00+06:00: “Keep these unset; I’ll provide different simulation values” and “Use seed 4242 and a 60/20/20 agent split”.

## 2026-10-02T13:10:37+06:00 — Approved local ports

Human: “Resume with API 18000 and frontend 13000”. T006 resumed using those localhost bindings; internal container ports stay 8000/80 and the existing PHP service remains running.

## 2026-10-02T14:43:31+06:00 — Public runtime deployment deferred

Human response to hosting-account question: “for now work in local”. Continue local work; public runtime deployment is deferred. The previously authorized GitHub remote and regular source pushes remain in use.
