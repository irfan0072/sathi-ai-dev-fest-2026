# On-site update preparation

Local verified baseline: code db41989; frozen model evidence ac18e14. Keep a clean checkout, pinned dependency files and the recorded local walkthrough. Preserve PostgreSQL; never remove volumes or replenish demo balances to hide policy failures.

1. Save the organizer's changed requirements in a task brief. Identify config-only policy changes versus schema/API/evaluation changes; obtain required human approval before changing the latter.
2. Review `data/config.yaml` and `data/assumptions.md`; label every simulation financial default ASSUMPTION. Update decisions and change log. Config changes invalidate the current frozen artifact hash: do not serve old scores as new-policy results.
3. Use new directories for approved data/evaluation runs. Retain disjoint agents/seeds, leakage guards, rule baselines, validation-only sanity ceiling, calibration caveat and held-out reporting. Never tune to the final test score.
4. For source updates run `make test lint build-console`, rebuild local containers and run `make smoke-skeleton`. Rehearse new request → Bangla confirmation → terminal issue → redeem → report/receipt and failure/review paths. UI/artifact errors must remain visible.
5. Record the exact changed source/config/artifact provenance, checks and limitations; commit/push within the organizer's announced window. Refresh the report/demo with real saved results. Existing model scores never decide cash-out.

Channel adapters can reuse existing mandate APIs, but no live provider/STT integration is claimed. Keep keypad, templates and baseline/evaluation; optional graph, voice and LLM work can remain omitted. Use the recorded local fallback if hosting is unavailable. The human confirms registration, equipment, account ownership, update-window timing and presentation readiness.
