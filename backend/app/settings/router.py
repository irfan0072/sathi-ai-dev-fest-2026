"""Analyst settings API: runtime options, provider credentials and connection tests.

All writes need the analyst role and are refused when SATHI_SETTINGS_EDITABLE=false.
Demo analyst PINs are public: on a public deployment, configure everything, then set
SATHI_SETTINGS_EDITABLE=false so the page becomes read-only.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.mandates.router import get_mandate_service
from app.settings import probes
from app.settings.credentials import E164, CredentialError, CredentialStore
from app.settings.service import SettingsError, SettingsService

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

PAID_TESTS_PER_HOUR = 5
TEST_ATTEMPTS_PER_HOUR = 20
# Settings change providers, credentials and policy for the whole platform: super admin only.
Analyst = Annotated[AuthenticatedPrincipal, Depends(require_roles("super_admin"))]


def get_settings() -> SettingsService:
    """Bound to the current mandate service database (tests swap it per schema)."""
    return SettingsService(get_mandate_service().get_connection)


def get_credentials() -> CredentialStore:
    return CredentialStore(get_mandate_service().get_connection)


def _err(status: int, code: str, message: str, key: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message, "key": key}})


def _settings_error(err: SettingsError) -> JSONResponse:
    if "read-only" in str(err):
        return _err(403, "SETTINGS_READ_ONLY", str(err), err.key)
    return _err(422, "SETTINGS_INVALID", str(err), err.key)


def _require_editable() -> JSONResponse | None:
    if not get_settings().editable():
        return _err(403, "SETTINGS_READ_ONLY", "Settings are read-only on this deployment.")
    return None


class SettingsUpdate(BaseModel):
    changes: dict[str, Any]


class CredentialsUpdate(BaseModel):
    values: dict[str, Any] = Field(..., max_length=20)


class TestTarget(BaseModel):
    to: str = Field(..., max_length=20)


@router.get("")
def read_settings(principal: Analyst) -> Any:
    body = get_settings().describe()
    body["credentials"] = {**get_credentials().status(), "editable": body["editable"]}
    return body


@router.put("")
def update_settings(body: SettingsUpdate, principal: Analyst) -> Any:
    try:
        return get_settings().update(body.changes, principal.subject)
    except SettingsError as err:
        return _settings_error(err)


@router.get("/readiness")
def readiness(principal: Analyst) -> Any:
    """What the selected providers still need. No network calls."""
    return get_settings().readiness()


@router.get("/probe")
def probe(principal: Analyst, only: str | None = None) -> Any:
    """Free, read-only connection checks with the effective credentials."""
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    from app.ops.readiness import PROBES, run_all, run_one

    env = get_credentials().effective_env()
    values = get_settings().values()
    env["SATHI_GEMINI_MODEL"] = values["ai.gemini_model"]
    env["SATHI_OPENAI_MODEL"] = values["ai.openai_model"]
    if only is not None and only not in PROBES:
        return _err(422, "UNKNOWN_PROBE", f"Unknown probe. Choose one of {', '.join(PROBES)}.")
    results = [run_one(only, env)] if only else run_all(env)
    return {"probes": [r.to_dict() for r in results]}


@router.get("/credentials")
def read_credentials(principal: Analyst) -> Any:
    return {**get_credentials().status(), "editable": get_settings().editable()}


@router.put("/credentials")
def update_credentials(body: CredentialsUpdate, principal: Analyst) -> Any:
    if (denied := _require_editable()) is not None:
        return denied
    store = get_credentials()
    try:
        saved = store.save(body.values, principal.subject)
    except CredentialError as err:
        return _err(422, "CREDENTIAL_INVALID", str(err), err.name)
    return {"saved": saved, **store.status(), "editable": True}


@router.delete("/credentials/{name}")
def clear_credential(name: str, principal: Analyst) -> Any:
    if (denied := _require_editable()) is not None:
        return denied
    store = get_credentials()
    try:
        removed = store.clear(name, principal.subject)
    except CredentialError as err:
        return _err(422, "CREDENTIAL_INVALID", str(err), err.name)
    return {"removed": removed, **store.status(), "editable": True}


@router.post("/providers/{provider}/test")
def test_provider(provider: str, principal: Analyst) -> Any:
    """Free, read-only connection test using the effective credentials."""
    from app.deployment import blocked_response, is_public_demo

    if is_public_demo():
        return blocked_response()
    env = get_credentials().effective_env()
    values = get_settings().values()
    checks = {
        "twilio": lambda: probes.probe_twilio(env),
        "alpha_sms": lambda: probes.probe_alpha(env),
        "gemini": lambda: probes.probe_gemini(env, values["ai.gemini_model"]),
        "openai": lambda: probes.probe_openai(env, values["ai.openai_model"]),
        "bd_ivr": lambda: probes.probe_bd_ivr(env),
        "webhooks": lambda: probes.probe_webhooks(env),
    }
    if provider not in checks:
        return _err(404, "UNKNOWN_PROVIDER", "Unknown provider.")
    result = checks[provider]()
    get_mandate_service().log_audit(principal.subject, "provider_tested", "credentials",
                                    provider, {"ok": result["ok"]})
    return result


def _paid_test(kind: str, to: str, principal: AuthenticatedPrincipal) -> Any:
    if (denied := _require_editable()) is not None:
        return denied
    if not re.fullmatch(E164, to.strip()):
        return _err(422, "INVALID_PHONE", "Use E.164 format, e.g. +8801XXXXXXXXX.", "to")
    service = get_mandate_service()
    # Only tests the provider accepted spend credit, so only those count toward the paid
    # limit. Refused attempts (unverified number, wrong settings) cost nothing; a looser cap
    # still stops the button being hammered.
    with service.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE (detail->>'ok')::boolean), count(*), "
            "min(ts) FILTER (WHERE (detail->>'ok')::boolean), min(ts) "
            "FROM audit_log WHERE action IN ('provider_test_call', 'provider_test_sms') "
            "AND ts > now() - interval '1 hour';"
        )
        paid, attempts, first_paid, first_any = cur.fetchone()
        limited = None
        if paid >= PAID_TESTS_PER_HOUR:
            limited = (first_paid, f"At most {PAID_TESTS_PER_HOUR} paid tests per hour.")
        elif attempts >= TEST_ATTEMPTS_PER_HOUR:
            limited = (first_any, f"At most {TEST_ATTEMPTS_PER_HOUR} test attempts per hour.")
        if limited:
            cur.execute("SELECT ceil(extract(epoch FROM (%s + interval '1 hour' - now())) / 60);",
                        (limited[0],))
            minutes = max(1, int(cur.fetchone()[0] or 1))
            return _err(429, "TEST_RATE_LIMITED",
                        f"{limited[1]} Try again in {minutes} minute(s).")
    env = get_credentials().effective_env()
    result = (probes.twilio_test_call(env, to.strip()) if kind == "call"
              else probes.alpha_test_sms(env, to.strip()))
    digits = re.sub(r"\D", "", to)
    service.log_audit(principal.subject, f"provider_test_{kind}", "credentials",
                      result["provider"], {"ok": result["ok"], "to": f"…{digits[-3:]}"})
    return result


@router.post("/providers/twilio/test-call")
def test_call(body: TestTarget, principal: Analyst) -> Any:
    return _paid_test("call", body.to, principal)


@router.post("/providers/alpha_sms/test-sms")
def test_sms(body: TestTarget, principal: Analyst) -> Any:
    return _paid_test("sms", body.to, principal)


@router.delete("/{key}")
def reset_setting(key: str, principal: Analyst) -> Any:
    try:
        return get_settings().reset(key, principal.subject)
    except SettingsError as err:
        return _settings_error(err)
