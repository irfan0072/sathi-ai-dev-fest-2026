"""Runtime settings: bounds, provider readiness, precedence, audit and live effect."""

from __future__ import annotations

import pytest
from app.copilot.investigator import clients_from_env
from app.main import app
from app.mandates.service import MandateService
from app.settings.service import SettingsError, SettingsService
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
ANALYST = {"Authorization": f"Bearer {create_test_token('admin_1', 'super_admin')}"}
FRAUD_ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_1', 'analyst')}"}
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
CUSTOMER = {"Authorization": f"Bearer {create_test_token('U_001', 'customer_channel')}"}


def _put(changes: dict) -> object:
    return client.put("/api/v1/settings", headers=ANALYST, json={"changes": changes})


def test_describe_lists_settings_and_hides_secrets(durable_service, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    monkeypatch.setenv("SATHI_VOICE_PHONE_BOOK", '{"U_001":"+8801712345678"}')
    res = client.get("/api/v1/settings", headers=ANALYST)
    assert res.status_code == 200
    body = res.json()
    assert "super-secret-value" not in res.text and "+8801712345678" not in res.text
    gemini = next(s for s in body["secrets"] if s["id"] == "gemini")
    assert gemini["configured"] is True
    assert body["phone_book"][0]["phone"].endswith("678")
    keys = {i["key"] for i in body["items"]}
    assert {"voice.provider", "risk.band_low_max", "ops.sla_urgent_minutes"} <= keys
    twilio = next(o for o in next(i for i in body["items"] if i["key"] == "voice.provider")[
        "options"] if o["value"] == "twilio")
    assert twilio["unavailable_reason"]
    assert client.get("/api/v1/settings", headers=AGENT).status_code == 403


def test_validation_bounds_and_cross_field(durable_service):
    assert _put({"risk.band_low_max": 2}).status_code == 422
    assert _put({"ops.sla_urgent_minutes": 2.5}).status_code == 422
    assert _put({"risk.band_low_max": 0.7, "risk.band_medium_max": 0.6}).status_code == 422
    assert _put({"ai.gemini_model": "x; drop table"}).status_code == 422
    assert _put({"unknown.key": 1}).status_code == 422
    res = _put({"voice.provider": "twilio"})
    assert res.status_code == 422 and res.json()["error"]["key"] == "voice.provider"


def test_override_precedence_reset_and_audit(durable_service: MandateService, monkeypatch):
    monkeypatch.setenv("SATHI_STEP_UP_ENFORCED", "true")
    svc = SettingsService(durable_service.get_connection)
    assert svc.get("risk.step_up_enforced") is True  # env
    body = _put({"risk.step_up_enforced": False, "ops.sla_urgent_minutes": 10}).json()
    item = next(i for i in body["items"] if i["key"] == "risk.step_up_enforced")
    assert item["value"] is False and item["source"] == "override"
    assert item["updated_by"] == "admin_1"
    reset = client.delete("/api/v1/settings/risk.step_up_enforced", headers=ANALYST).json()
    assert next(i for i in reset["items"] if i["key"] == "risk.step_up_enforced")["source"] == "env"
    actions = [a["action"] for a in durable_service.audit_log]
    assert "settings_updated" in actions and "settings_reset" in actions


def test_read_only_deployment(durable_service, monkeypatch):
    monkeypatch.setenv("SATHI_SETTINGS_EDITABLE", "false")
    assert client.get("/api/v1/settings", headers=ANALYST).json()["editable"] is False
    res = _put({"ops.sla_urgent_minutes": 20})
    assert res.status_code == 403 and res.json()["error"]["code"] == "SETTINGS_READ_ONLY"


def test_settings_change_live_behavior(durable_service: MandateService):
    # Response target drives the prioritized queue.
    durable_service.create_case(None, "A_001", "duress_signal", {})
    _put({"ops.sla_urgent_minutes": 5})
    case = client.get("/api/v1/ops/cases", headers=ANALYST).json()["cases"][0]
    assert case["sla_minutes"] == 5

    # Step-up enforcement from settings blocks app keypad for a medium band.
    _put({"risk.step_up_enforced": True, "risk.band_low_max": 0.05,
          "risk.band_medium_max": 0.99})
    req = client.post("/api/v1/mandates/request", headers=AGENT,
                      json={"user_id": "U_001", "agent_id": "A_001", "amount": 1000}).json()
    assert req["risk"]["band"] == "medium"
    res = client.post(f"/api/v1/mandates/{req['mandate_id']}/verify", headers=CUSTOMER,
                      json={"mode": "keypad", "stated_amount": 1000})
    assert res.status_code == 403 and res.json()["error"]["code"] == "STEP_UP_REQUIRED"

    cfg = client.get("/api/v1/voice/config", headers=AGENT).json()
    assert cfg["step_up_enforced"] is True and cfg["provider"] == "simulated"


def test_unit_costs_follow_assumptions(durable_service):
    costs = _put({"cost.usd_to_bdt": 120, "cost.twilio_usd_per_min": 0.06,
                  "cost.avg_call_seconds": 60}).json()["unit_costs"]
    assert costs["twilio_bdt_per_call"] == pytest.approx(7.2)


def test_ai_provider_order():
    env = {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"}
    assert [c.name for c in clients_from_env(env)] == ["gemini", "openai"]
    assert [c.name for c in clients_from_env(env, order="openai_first")] == ["openai", "gemini"]
    assert clients_from_env(env, order="template_only") == []
    assert clients_from_env(env, gemini_model="gemini-2.5-pro")[0].model == "gemini-2.5-pro"


def test_coerce_errors_name_the_key(durable_service):
    svc = SettingsService(durable_service.get_connection)
    with pytest.raises(SettingsError) as err:
        svc.update({"cost.sms_bdt": "abc"}, "a")
    assert err.value.key == "cost.sms_bdt"


# ---------------------------------------------------------------------------
# Go-live readiness panel + live probe endpoint
# ---------------------------------------------------------------------------
def test_readiness_reports_missing_env_for_each_provider(durable_service):
    """No env vars are set; readiness should report every panel as
    `not selected` (voice=sms because simulated is the default) but the
    secret-bearing panels must show env_vars missing."""
    res = client.get("/api/v1/settings/readiness", headers=ANALYST)
    assert res.status_code == 200
    body = res.json()
    # Defaults: voice=simulated, sms=simulated, ai=gemini_first
    assert body["selected"]["voice_provider"] == "simulated"
    assert body["selected"]["sms_provider"] == "simulated"
    assert body["selected"]["ai_provider_order"] == "gemini_first"
    assert body["selected"]["public_url_ok"] is False
    # Twilio and BD IVR are "not selected" because simulated is default.
    for panel_id in ("twilio", "bd_http_ivr"):
        p = next(x for x in body["panels"] if x["provider_id"] == panel_id)
        assert p["selected"] is False
        assert p["ready"] is False
        assert all(v["set"] is False for v in p["env_vars"])
        assert p["hint"]  # human-readable hint is present
    # Gemini is selected (gemini_first is default), but the env is missing.
    gemini = next(x for x in body["panels"] if x["provider_id"] == "gemini")
    assert gemini["selected"] is True
    assert gemini["ready"] is False
    assert next(v for v in gemini["env_vars"] if v["name"] == "GEMINI_API_KEY")["set"] is False


def test_readiness_flips_to_ready_when_env_is_present(
    durable_service, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "real-key")
    body = client.get("/api/v1/settings/readiness", headers=ANALYST).json()
    gemini = next(x for x in body["panels"] if x["provider_id"] == "gemini")
    assert gemini["ready"] is True
    # OpenAI is the fallback under gemini_first; not selected but env is
    # missing so the report should flag it as not-ready-but-not-selected.
    openai = next(x for x in body["panels"] if x["provider_id"] == "openai")
    assert openai["selected"] is True   # part of the chain under gemini_first
    assert openai["ready"] is False
    assert body["all_ready"] is False


def test_readiness_requires_https_public_url_for_voice_providers(
    durable_service, monkeypatch
):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550007")
    monkeypatch.setenv("SATHI_PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("GEMINI_API_KEY", "real-key")
    monkeypatch.setenv("OPENAI_API_KEY", "real-key")
    # Flip voice.provider to twilio. provider_ready() now passes because
    # public URL is https and twilio creds are set.
    res = _put({"voice.provider": "twilio"})
    assert res.status_code == 200, res.text
    body = client.get("/api/v1/settings/readiness", headers=ANALYST).json()
    twilio = next(x for x in body["panels"] if x["provider_id"] == "twilio")
    assert twilio["selected"] is True
    assert twilio["ready"] is True
    # With Gemini+OpenAI keys set, the default gemini_first AI chain is also
    # fully ready, so all_ready flips to True.
    assert body["all_ready"] is True


def test_readiness_flags_missing_public_url_via_provider_gating(
    durable_service, monkeypatch
):
    """provider_ready() refuses a write to twilio when SATHI_PUBLIC_API_URL
    is not https. The readiness report should reflect that twilio is the
    *gating* missing piece, even when env is otherwise set."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15005550007")
    # No public URL set.
    res = _put({"voice.provider": "twilio"})
    assert res.status_code == 422
    # voice.provider stays at simulated, so twilio panel reports
    # selected=False; readiness only flips when the operator both sets
    # env vars AND flips the selector.
    body = client.get("/api/v1/settings/readiness", headers=ANALYST).json()
    twilio = next(x for x in body["panels"] if x["provider_id"] == "twilio")
    assert twilio["selected"] is False


def test_readiness_is_analyst_only(durable_service):
    assert client.get("/api/v1/settings/readiness",
                      headers=AGENT).status_code == 403
    assert client.get("/api/v1/settings/readiness",
                      headers=CUSTOMER).status_code == 403


def test_probe_endpoint_returns_one_or_all_results(durable_service):
    # No probes are run if a probe is requested that does not exist.
    res = client.get("/api/v1/settings/probe?only=does-not-exist", headers=ANALYST)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "UNKNOWN_PROBE"

    # With no env, every provider either skips or is skipped; never burns
    # credits, never raises.
    res = client.get("/api/v1/settings/probe", headers=ANALYST)
    assert res.status_code == 200
    names = {p["name"] for p in res.json()["probes"]}
    assert names == {"twilio", "alpha_sms", "gemini", "openai", "bd_http_ivr"}
    # Every probe is one of: env_ok=True → probe was actually run;
    # env_ok=False → probe was skipped because env is absent.
    for p in res.json()["probes"]:
        assert "name" in p and "env_ok" in p and "probe_ok" in p
        assert "detail" in p and "ready" in p


def test_probe_endpoint_is_analyst_only(durable_service):
    assert client.get("/api/v1/settings/probe", headers=AGENT).status_code == 403
    assert client.get("/api/v1/settings/probe", headers=CUSTOMER).status_code == 403


def test_settings_are_super_admin_only():
    for role, sub in (("analyst", "analyst_1"), ("supervisor", "sup_1"), ("agent", "A_001")):
        h = {"Authorization": f"Bearer {create_test_token(sub, role)}"}
        assert client.get("/api/v1/settings", headers=h).status_code == 403
        assert client.put("/api/v1/settings", headers=h,
                          json={"changes": {"sim.enabled": True}}).status_code == 403
