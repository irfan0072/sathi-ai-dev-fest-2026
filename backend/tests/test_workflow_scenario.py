"""The synthetic end-to-end scenario runs through the real backend and produces evidence."""

from __future__ import annotations

import pytest
from app.ops.demo_scenario import run_scenario


@pytest.fixture
def result(durable_service):
    return run_scenario(durable_service)


def test_every_scenario_runs_through_real_routes(result):
    scenarios = {s["scenario"] for s in result["steps"]}
    assert {s.split(" ")[0] for s in scenarios} >= {"S1", "S2", "S3", "S4", "S5", "S6", "S6b",
                                                    "S7", "Evidence"}
    assert result["label"].startswith("SYNTHETIC")
    # Role and ownership denials really happened with the codes the API returns.
    denials = [s for s in result["steps"] if s["scenario"].startswith("S7")]
    assert {s["http"] for s in denials} == {401, 403}


def test_evidence_is_computed_from_the_events_with_denominators(result):
    ev = result["workflow_evidence"]
    assert ev["field_impact"] is None and "No real pilot data" in ev["field_impact_note"]
    assert ev["environment"]["voice_provider"] == "simulated"
    calls = ev["calls"]
    assert calls["attempted"] >= 9 and calls["answered"]["denominator"] == calls["attempted"]
    assert calls["completed_with_a_clear_outcome"]["numerator"] >= 5
    assert calls["failed_to_place"]["numerator"] >= 4          # S6 and S6b provider outages
    assert calls["unclear"]["numerator"] >= 1                  # S5
    assert ev["retries"]["checks_with_more_than_one_call"] >= 2
    assert ev["delivery_recovery"]["handed_to_a_person_after_provider_failure"] == 1
    assert ev["manual_handling"]["resolved_by_a_person"] >= 1
    cases = ev["cases"]
    assert cases["total"] == 2 and cases["from_post_cash_out_checks"] == 2
    assert cases["confirmed_problem"] == 1 and cases["escalated"] == 1
    assert cases["cleared_no_wrongdoing_found"] == 0           # nothing was cleared without contact
    assert "not recovered money" in cases["meaning"]
    followup = ev["independent_followup"]["by_status"]
    assert followup.get("reached_independently") == 1 and followup.get("uncertain") == 1
    assert ev["independent_followup"]["unresolved"] == 1
    assert ev["privacy"]["audio_stored"] is False
    assert ev["audit_trail"]["events"] > 20


def test_economics_baseline_is_assumption_only_and_negative_without_an_intervention(result):
    base = result["economics_baseline"]
    assert base["benefit"]["total"] == 0 and base["net"] < 0


def test_audit_trail_records_the_human_decision(result, durable_service):
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT action FROM audit_log WHERE action LIKE 'CASE_DECISION_%' "
                    "ORDER BY log_id;")
        assert [r[0] for r in cur.fetchall()] == ["CASE_DECISION_DENIED", "CASE_DECISION_ESCALATED"]
        cur.execute("SELECT count(*) FROM audit_log WHERE action = 'followup_recorded';")
        assert cur.fetchone()[0] == 3
