"""Connection tests for third-party providers.

Each probe makes one read-only, free request that proves the credentials work, except the
explicit test call and test SMS, which cost money and are rate-limited by the router.
Results never contain credential values.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

Opener = Callable[..., Any]


def _request(url: str, headers: dict[str, str] | None = None, data: bytes | None = None,
             method: str = "GET", opener: Opener = urllib.request.urlopen,
             timeout: float = 10.0) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode() or "{}"
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, None


def _result(provider: str, started: float, ok: bool, detail: str,
            http_status: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"provider": provider, "ok": ok, "detail": detail, "http_status": http_status,
            "latency_ms": round((time.monotonic() - started) * 1000), **extra}


def _missing(provider: str, names: list[str]) -> dict[str, Any]:
    return {"provider": provider, "ok": False, "http_status": None, "latency_ms": 0,
            "detail": "Missing: " + ", ".join(names)}


def _need(env: dict[str, str], names: list[str]) -> list[str]:
    return [n for n in names if not env.get(n, "").strip()]


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def probe_twilio(env: dict[str, str], opener: Opener = urllib.request.urlopen) -> dict:
    missing = _need(env, ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"])
    if missing:
        return _missing("twilio", missing)
    started = time.monotonic()
    sid = env["TWILIO_ACCOUNT_SID"]
    try:
        status, data = _request(
            f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}.json",
            {"Authorization": _basic(sid, env["TWILIO_AUTH_TOKEN"])}, opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("twilio", started, False, "Twilio is unreachable.")
    if status == 200 and data:
        return _result("twilio", started, data.get("status") == "active",
                       f"Account {data.get('status')} ({data.get('type', 'unknown')} account).",
                       status, account_type=data.get("type"))
    if status in (401, 403, 404):
        return _result("twilio", started, False, "Twilio rejected the Account SID or token.",
                       status)
    return _result("twilio", started, False, f"Unexpected Twilio response (HTTP {status}).",
                   status)


def probe_alpha(env: dict[str, str], opener: Opener = urllib.request.urlopen) -> dict:
    if _need(env, ["ALPHA_SMS_API_KEY"]):
        return _missing("alpha_sms", ["ALPHA_SMS_API_KEY"])
    started = time.monotonic()
    query = urllib.parse.urlencode({"api_key": env["ALPHA_SMS_API_KEY"]})
    try:
        status, data = _request(f"https://api.sms.net.bd/user/balance/?{query}", opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("alpha_sms", started, False, "Alpha SMS is unreachable.")
    if status == 200 and data and data.get("error") == 0:
        balance = (data.get("data") or {}).get("balance")
        return _result("alpha_sms", started, True, f"Key accepted. Balance ৳{balance}.", status,
                       balance=balance)
    code = data.get("error") if data else None
    return _result("alpha_sms", started, False,
                   f"Alpha SMS rejected the key (error {code}).", status)


def probe_gemini(env: dict[str, str], model: str,
                 opener: Opener = urllib.request.urlopen) -> dict:
    if _need(env, ["GEMINI_API_KEY"]):
        return _missing("gemini", ["GEMINI_API_KEY"])
    started = time.monotonic()
    try:
        status, data = _request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model)}",
            {"x-goog-api-key": env["GEMINI_API_KEY"]}, opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("gemini", started, False, "Gemini API is unreachable.")
    if status == 200 and data:
        return _result("gemini", started, True,
                       f"Key accepted. Model {data.get('displayName', model)} available.", status)
    if status == 404:
        return _result("gemini", started, False, f"Model '{model}' not found for this key.",
                       status)
    return _result("gemini", started, False, "Gemini rejected the API key.", status)


def probe_openai(env: dict[str, str], model: str,
                 opener: Opener = urllib.request.urlopen) -> dict:
    if _need(env, ["OPENAI_API_KEY"]):
        return _missing("openai", ["OPENAI_API_KEY"])
    started = time.monotonic()
    try:
        status, data = _request(
            f"https://api.openai.com/v1/models/{urllib.parse.quote(model)}",
            {"Authorization": f"Bearer {env['OPENAI_API_KEY']}"}, opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("openai", started, False, "OpenAI API is unreachable.")
    if status == 200 and data:
        return _result("openai", started, True, f"Key accepted. Model {data.get('id')} available.",
                       status)
    if status == 404:
        return _result("openai", started, False, f"Model '{model}' not available to this key.",
                       status)
    return _result("openai", started, False, "OpenAI rejected the API key.", status)


def probe_bd_ivr(env: dict[str, str], opener: Opener = urllib.request.urlopen) -> dict:
    missing = _need(env, ["SATHI_BD_IVR_BASE_URL", "SATHI_BD_IVR_API_KEY",
                          "SATHI_BD_IVR_WEBHOOK_SECRET"])
    if missing:
        return _missing("bd_ivr", missing)
    started = time.monotonic()
    try:
        status, _ = _request(env["SATHI_BD_IVR_BASE_URL"],
                             {"Authorization": f"Bearer {env['SATHI_BD_IVR_API_KEY']}"},
                             opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("bd_ivr", started, False, "Gateway is unreachable.")
    if status in (401, 403):
        return _result("bd_ivr", started, False, "Gateway rejected the API key.", status)
    if status < 500:
        return _result("bd_ivr", started, True,
                       f"Gateway reachable (HTTP {status}). The key is fully verified on the "
                       "first call, because gateways have no common test endpoint.", status)
    return _result("bd_ivr", started, False, f"Gateway error (HTTP {status}).", status)


def probe_webhooks(env: dict[str, str], opener: Opener = urllib.request.urlopen) -> dict:
    if _need(env, ["SATHI_PUBLIC_API_URL"]):
        return _missing("webhooks", ["SATHI_PUBLIC_API_URL"])
    started = time.monotonic()
    base = env["SATHI_PUBLIC_API_URL"].rstrip("/")
    if not base.startswith("https://"):
        return _result("webhooks", started, False, "Public API URL must use https.")
    try:
        status, data = _request(f"{base}/health", opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("webhooks", started, False,
                       "Public URL is unreachable from this server. Providers could not "
                       "deliver call events.")
    if status == 200 and data and data.get("status") == "ok":
        return _result("webhooks", started, True, "Public URL reaches this API (health ok).",
                       status)
    return _result("webhooks", started, False,
                   f"Public URL answered HTTP {status}, not a healthy Sathi API.", status)


def twilio_test_call(env: dict[str, str], to_number: str,
                     opener: Opener = urllib.request.urlopen) -> dict:
    """Short Bangla test message; inline TwiML so no webhook is needed."""
    missing = _need(env, ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"])
    if missing:
        return _missing("twilio", missing)
    started = time.monotonic()
    sid = env["TWILIO_ACCOUNT_SID"]
    xml = ('<Response><Say language="bn-IN" voice="Google.bn-IN-Standard-A">'
           'এটি সাথী পরীক্ষামূলক কল। আপনার সেটআপ কাজ করছে। ধন্যবাদ।</Say></Response>')
    body = urllib.parse.urlencode({"To": to_number, "From": env["TWILIO_FROM_NUMBER"],
                                   "Twiml": xml}).encode()
    try:
        status, data = _request(
            f"https://api.twilio.com/2010-04-01/Accounts/{urllib.parse.quote(sid)}/Calls.json",
            {"Authorization": _basic(sid, env["TWILIO_AUTH_TOKEN"]),
             "Content-Type": "application/x-www-form-urlencoded"},
            data=body, method="POST", opener=opener)
    except (urllib.error.URLError, TimeoutError):
        return _result("twilio", started, False, "Twilio is unreachable.")
    if status in (200, 201) and data and data.get("sid"):
        return _result("twilio", started, True, "Test call placed. Your phone should ring.",
                       status, call_sid=data["sid"])
    if status == 400:
        return _result("twilio", started, False,
                       "Twilio refused the number. Trial accounts can only call verified "
                       "numbers, and Bangladesh must be enabled in Voice geo permissions.", status)
    return _result("twilio", started, False, f"Twilio rejected the call (HTTP {status}).", status)


def alpha_test_sms(env: dict[str, str], to_number: str,
                   opener: Opener = urllib.request.urlopen) -> dict:
    from app.notify.service import AlphaSmsProvider

    if _need(env, ["ALPHA_SMS_API_KEY"]):
        return _missing("alpha_sms", ["ALPHA_SMS_API_KEY"])
    started = time.monotonic()
    result = AlphaSmsProvider(env["ALPHA_SMS_API_KEY"], env.get("ALPHA_SMS_SENDER_ID", ""),
                              opener=opener).send(to_number,
                                                  "সাথী: পরীক্ষামূলক বার্তা। আপনার SMS সেটআপ কাজ করছে।")
    if result.status == "sent":
        return _result("alpha_sms", started, True, "Test SMS submitted.",
                       request_id=result.provider_ref)
    return _result("alpha_sms", started, False, result.error or "SMS failed.")
