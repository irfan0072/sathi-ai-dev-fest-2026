"""Provider credentials: encryption, write-only API, read-only switch, precedence, probes."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest
from app.main import app
from app.mandates.service import MandateService
from app.settings import probes
from app.settings import router as settings_router
from app.settings.credentials import CredentialStore
from app.voice import router as voice_router
from fastapi.testclient import TestClient
from tests.conftest import create_test_token

client = TestClient(app)
ANALYST = {"Authorization": f"Bearer {create_test_token('admin_1', 'super_admin')}"}
FRAUD_ANALYST = {"Authorization": f"Bearer {create_test_token('analyst_1', 'analyst')}"}
AGENT = {"Authorization": f"Bearer {create_test_token('A_001', 'agent', ['U_001'])}"}
SID = "AC" + "a" * 32
TOKEN = "b" * 32


@pytest.fixture
def secured(monkeypatch, durable_service: MandateService):
    monkeypatch.setenv("SATHI_SECRETS_KEY", "k" * 40)
    for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
                 "SATHI_PUBLIC_API_URL", "SATHI_VOICE_PHONE_BOOK", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    voice_router.set_voice_service(None)
    return ANALYST


def _save(headers, values):
    return client.put("/api/v1/settings/credentials", headers=headers, json={"values": values})


# ------------------------------------------------------------------- access
def test_only_analysts_manage_credentials(secured):
    assert _save(AGENT, {"GEMINI_API_KEY": "x" * 30}).status_code == 403
    assert client.get("/api/v1/settings/credentials", headers=AGENT).status_code == 403
    assert _save(secured, {"GEMINI_API_KEY": "x" * 30}).status_code == 200


def test_read_only_deployment_blocks_credentials_and_paid_tests(secured, monkeypatch):
    monkeypatch.setenv("SATHI_SETTINGS_EDITABLE", "false")
    res = _save(secured, {"GEMINI_API_KEY": "x" * 30})
    assert res.status_code == 403 and res.json()["error"]["code"] == "SETTINGS_READ_ONLY"
    assert client.delete("/api/v1/settings/credentials/GEMINI_API_KEY",
                         headers=secured).status_code == 403
    assert client.post("/api/v1/settings/providers/twilio/test-call", headers=secured,
                       json={"to": "+8801712345678"}).status_code == 403
    assert client.get("/api/v1/settings/credentials", headers=secured).json()["editable"] is False


# ------------------------------------------------------------------- storage
def test_saved_secret_is_encrypted_write_only_and_audited(secured,
                                                          durable_service: MandateService):
    secret = "AIza" + "S" * 30 + "WXYZ"
    res = _save(secured, {"GEMINI_API_KEY": secret})
    assert res.status_code == 200 and res.json()["saved"] == ["GEMINI_API_KEY"]
    status = client.get("/api/v1/settings", headers=ANALYST)
    assert secret not in status.text
    item = next(i for i in status.json()["credentials"]["items"]
                if i["name"] == "GEMINI_API_KEY")
    assert item["source"] == "settings" and item["hint"] == "••••WXYZ"
    assert item["updated_by"] == "admin_1"
    with durable_service.get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT ciphertext FROM provider_credentials;")
        assert secret not in cur.fetchone()[0]
        cur.execute("SELECT detail::text FROM audit_log WHERE action = 'credentials_updated';")
        assert secret not in cur.fetchone()[0]
    assert CredentialStore(durable_service.get_connection).effective_env()["GEMINI_API_KEY"] \
        == secret


def test_validation_names_the_field(secured):
    res = _save(secured, {"TWILIO_ACCOUNT_SID": "XX123"})
    assert res.status_code == 422 and res.json()["error"]["key"] == "TWILIO_ACCOUNT_SID"
    assert _save(secured, {"SATHI_PUBLIC_API_URL": "http://insecure.example"}).status_code == 422
    assert _save(secured, {"SATHI_VOICE_PHONE_BOOK": {"U_001": "017123"}}).status_code == 422
    assert _save(secured, {"OPENAI_API_KEY": "sk-abc\ninjected"}).status_code == 422
    assert _save(secured, {"NOT_A_CREDENTIAL": "x"}).status_code == 422


def test_precedence_clear_and_key_rotation(secured, durable_service, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-value-env-value-env-value")
    store = CredentialStore(durable_service.get_connection)
    assert store.effective_env()["GEMINI_API_KEY"].startswith("env-value")
    _save(secured, {"GEMINI_API_KEY": "db-value-db-value-db-value-1234"})
    assert store.effective_env()["GEMINI_API_KEY"].startswith("db-value")
    res = client.delete("/api/v1/settings/credentials/GEMINI_API_KEY", headers=secured).json()
    assert res["removed"] is True
    assert store.effective_env()["GEMINI_API_KEY"].startswith("env-value")

    _save(secured, {"GEMINI_API_KEY": "db-value-db-value-db-value-1234"})
    monkeypatch.setenv("SATHI_SECRETS_KEY", "z" * 40)  # key rotated without re-entry
    item = next(i for i in CredentialStore(durable_service.get_connection).status()["items"]
                if i["name"] == "GEMINI_API_KEY")
    assert item["source"] == "unreadable"


def test_without_encryption_key_saving_is_refused(durable_service, monkeypatch):
    monkeypatch.delenv("SATHI_SECRETS_KEY", raising=False)
    res = _save(ANALYST, {"GEMINI_API_KEY": "x" * 30})
    assert res.status_code == 422 and "SATHI_SECRETS_KEY" in res.json()["error"]["message"]


def test_ui_credentials_switch_live_provider(secured, durable_service):
    assert client.put("/api/v1/settings", headers=secured,
                      json={"changes": {"voice.provider": "twilio"}}).status_code == 422
    _save(secured, {"TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": TOKEN,
                    "TWILIO_FROM_NUMBER": "+12025550123",
                    "SATHI_PUBLIC_API_URL": "https://sathi-api.example.com",
                    "SATHI_VOICE_PHONE_BOOK": {"U_001": "+8801712345678"}})
    res = client.put("/api/v1/settings", headers=secured,
                     json={"changes": {"voice.provider": "twilio"}})
    assert res.status_code == 200
    service = voice_router.get_voice_service()
    assert service.provider.name == "twilio"
    assert service.phone_book == {"U_001": "+8801712345678"}
    assert service.public_base_url == "https://sathi-api.example.com"
    cfg = client.get("/api/v1/voice/config", headers=AGENT).json()
    assert cfg["live_calls"] is True and cfg["public_webhook_configured"] is True
    book = next(i for i in client.get("/api/v1/settings", headers=ANALYST).json()[
        "credentials"]["items"] if i["name"] == "SATHI_VOICE_PHONE_BOOK")
    assert book["entries"][0]["phone"].endswith("678") and "1234" not in book["entries"][0][
        "phone"]
    voice_router.set_voice_service(None)


# ------------------------------------------------------------------- probes
class _Resp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(status: int, body: dict | None = None, seen: list | None = None):
    def open_(request, timeout):
        if seen is not None:
            seen.append(request)
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "err", {}, None)
        return _Resp(json.dumps(body or {}).encode(), status)
    return open_


TW = {"TWILIO_ACCOUNT_SID": SID, "TWILIO_AUTH_TOKEN": TOKEN, "TWILIO_FROM_NUMBER": "+1202555"}


def test_probe_twilio():
    seen = []
    ok = probes.probe_twilio(TW, _opener(200, {"status": "active", "type": "Trial"}, seen))
    assert ok["ok"] and "Trial" in ok["detail"]
    assert seen[0].full_url.endswith(f"/Accounts/{SID}.json")
    assert TOKEN not in json.dumps(ok)
    assert not probes.probe_twilio(TW, _opener(401))["ok"]
    assert "Missing" in probes.probe_twilio({})["detail"]


def test_probe_alpha_gemini_openai_bd_webhooks():
    alpha = probes.probe_alpha({"ALPHA_SMS_API_KEY": "key12345"},
                               _opener(200, {"error": 0, "data": {"balance": "120.50"}}))
    assert alpha["ok"] and alpha["balance"] == "120.50"
    assert not probes.probe_alpha({"ALPHA_SMS_API_KEY": "key12345"},
                                  _opener(200, {"error": 405}))["ok"]
    seen = []
    assert probes.probe_gemini({"GEMINI_API_KEY": "g" * 30}, "gemini-2.5-flash",
                               _opener(200, {"displayName": "Gemini 2.5 Flash"}, seen))["ok"]
    assert seen[0].headers["X-goog-api-key"] == "g" * 30
    assert "not found" in probes.probe_gemini({"GEMINI_API_KEY": "g" * 30}, "nope",
                                              _opener(404))["detail"]
    assert probes.probe_openai({"OPENAI_API_KEY": "sk-" + "o" * 30}, "gpt-4o",
                               _opener(200, {"id": "gpt-4o"}))["ok"]
    assert not probes.probe_openai({"OPENAI_API_KEY": "sk-" + "o" * 30}, "gpt-4o",
                                   _opener(401))["ok"]
    bd = {"SATHI_BD_IVR_BASE_URL": "https://gw.example", "SATHI_BD_IVR_API_KEY": "k" * 10,
          "SATHI_BD_IVR_WEBHOOK_SECRET": "s" * 20}
    assert probes.probe_bd_ivr(bd, _opener(404))["ok"]
    assert not probes.probe_bd_ivr(bd, _opener(401))["ok"]
    assert probes.probe_webhooks({"SATHI_PUBLIC_API_URL": "https://api.example"},
                                 _opener(200, {"status": "ok"}))["ok"]
    assert not probes.probe_webhooks({"SATHI_PUBLIC_API_URL": "https://api.example"},
                                     _opener(503))["ok"]


def test_twilio_test_call_uses_inline_twiml():
    seen = []
    result = probes.twilio_test_call(TW, "+8801712345678", _opener(201, {"sid": "CA1"}, seen))
    assert result["ok"] and result["call_sid"] == "CA1"
    form = urllib.parse.parse_qs(seen[0].data.decode())
    assert form["To"] == ["+8801712345678"] and "<Say" in form["Twiml"][0]
    assert "trial" in probes.twilio_test_call(TW, "+880171", _opener(400))["detail"].lower()


def test_test_endpoints_audit_and_rate_limit(secured, durable_service, monkeypatch):
    monkeypatch.setattr(probes, "probe_gemini", lambda env, model: {
        "provider": "gemini", "ok": True, "detail": "ok", "http_status": 200, "latency_ms": 1})
    res = client.post("/api/v1/settings/providers/gemini/test", headers=ANALYST)
    assert res.status_code == 200 and res.json()["ok"]
    assert client.post("/api/v1/settings/providers/nope/test", headers=ANALYST).status_code == 404

    monkeypatch.setattr(probes, "alpha_test_sms", lambda env, to: {
        "provider": "alpha_sms", "ok": True, "detail": "sent", "http_status": None,
        "latency_ms": 1})
    url = "/api/v1/settings/providers/alpha_sms/test-sms"
    assert client.post(url, headers=AGENT, json={"to": "+8801712345678"}).status_code == 403
    assert client.post(url, headers=secured, json={"to": "01712"}).status_code == 422
    codes = [client.post(url, headers=secured, json={"to": "+8801712345678"}).status_code
             for _ in range(settings_router.PAID_TESTS_PER_HOUR + 1)]
    assert codes[:-1] == [200] * settings_router.PAID_TESTS_PER_HOUR and codes[-1] == 429
    actions = [a for a in durable_service.audit_log if a["action"] == "provider_test_sms"]
    assert actions and actions[0]["detail"]["to"] == "…678"


def test_init_env_generates_runtime_secrets_once(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "init_env", Path(__file__).resolve().parents[2] / "scripts" / "init_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = tmp_path / ".env"
    env.write_text("JWT_SECRET=x\nSATHI_SECRETS_KEY=CHANGE_ME\n")
    assert module.ensure_runtime_secrets(env) == ["SATHI_SECRETS_KEY"]
    first = env.read_text()
    assert "CHANGE_ME" not in first and first.count("SATHI_SECRETS_KEY=") == 1
    assert module.ensure_runtime_secrets(env) == [] and env.read_text() == first
