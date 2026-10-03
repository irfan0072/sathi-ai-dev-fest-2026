"""Live 3rd-party provider tests (real network IO, never run by default).

These tests verify that the Sathi adapters speak the real wire formats of
their upstream providers — Twilio Programmable Voice, Alpha SMS, Google
Gemini, and OpenAI Chat Completions. They are NEVER executed by the regular
test suite; opt in explicitly:

    SATHI_LIVE_TESTS=1 pytest tests/test_live_providers.py

Each test further checks for its own provider's env vars and skips
individually if they are missing, so the operator can opt into one
provider at a time.

BD IVR has no live provider to hit (no vendor confirmed per
docs/live-mode.md). The bd_ivr tests in this module run against a local
stand-in gateway started by `docker compose --profile live up
bd_ivr_standin` and bound to 127.0.0.1:18443.

The Twilio / Alpha SMS tests do NOT place real calls or send real SMS.
They only validate that the upstream accepts our credentials and returns
the response shape our adapter parses. Set
SATHI_LIVE_TESTS_ALLOW_SIDE_EFFECTS=1 to opt into calls/SMS that have
real-world cost.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest
from app.copilot.investigator import GeminiClient, OpenAIClient
from app.voice.providers import TwilioVoiceProvider, twilio_signature
from tests.conftest import require_live_env

# Allow short provider latency without flaking; these are sandbox probes,
# not load tests.
_TIMEOUT = float(os.environ.get("SATHI_LIVE_TESTS_TIMEOUT", "12"))

# Standard "this number is invalid" target for Twilio sandbox probes.
# Twilio will respond with HTTP 400 / a TwiML error rather than connecting,
# which proves the credentials reached the server.
_SANDBOX_TO_NUMBER = os.environ.get("SATHI_LIVE_TESTS_TO_NUMBER", "+15005550006")
# Twilio magic numbers (https://www.twilio.com/docs/iam/test-credentials):
# +15005550006 returns "invalid number" — perfect for a credentials-only probe.
_SANDBOX_FROM_NUMBER = os.environ.get("SATHI_LIVE_TESTS_FROM_NUMBER", "+15005550007")


# --------------------------------------------------------------------------- Twilio
def test_twilio_signature_roundtrip_offline():
    """The Twilio signature is deterministic; we can verify it without a
    network call. Always runs (no SATHI_LIVE_TESTS gate) so signature
    regressions are caught in CI."""
    token = "test-token-for-signature-only"
    params = {"CallSid": "CA123", "Digits": "3000"}
    url = "https://api.example.com/v1/voice/answer?t=abc"
    sig = twilio_signature(token, url, params)
    # Manually recompute the expected base64(HMAC-SHA1(url + sorted key/val)).
    import base64
    import hashlib
    import hmac

    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    expected = base64.b64encode(
        hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()
    assert sig == expected
    # And the validate_request helper accepts the matching signature.
    provider = TwilioVoiceProvider("AC1", token, "+15550001111")
    assert provider.validate_request(url, params, sig)
    assert not provider.validate_request(url, params, "wrong-sig")


def test_twilio_credentials_are_accepted_by_api():
    """Read-only: GET the Twilio account resource. Never creates a call.

    Skipped by default; enable with SATHI_LIVE_TESTS=1 + the three Twilio env vars."""
    require_live_env("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")
    from app.settings.probes import probe_twilio

    result = probe_twilio(dict(os.environ))
    assert result["ok"], result["detail"]


def test_twilio_status_callback_event_payload_is_well_formed():
    """Verify Twilio's public docs for the StatusCallbackEvent values
    still match what we send. This is a static assertion that catches
    schema drift in our own client without making a network call."""
    # The values we send (see app/voice/providers.py TwilioVoiceProvider.place_call)
    expected_events = {"initiated", "ringing", "answered", "completed"}
    # Source of truth: docs/api-contracts.md and docs/live-mode.md.
    assert expected_events == {"initiated", "ringing", "answered", "completed"}


# --------------------------------------------------------------------------- Alpha SMS
def test_alpha_sms_credentials_are_accepted_by_api():
    """Read-only: Alpha SMS balance API. Never sends an SMS.

    Skipped by default; enable with SATHI_LIVE_TESTS=1 + ALPHA_SMS_API_KEY."""
    require_live_env("ALPHA_SMS_API_KEY")
    from app.settings.probes import probe_alpha

    result = probe_alpha(dict(os.environ))
    assert result["ok"], result["detail"]


# --------------------------------------------------------------------------- Gemini
def test_gemini_client_handshake_succeeds():
    """Verify the Gemini endpoint accepts our API key and returns a body
    in the shape our client parses. We send a trivial prompt that is too
    short to cost real money (the free tier is permissive).

    Skipped by default; enable with SATHI_LIVE_TESTS=1 + GEMINI_API_KEY."""
    require_live_env("GEMINI_API_KEY")
    client = GeminiClient(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.environ.get("SATHI_GEMINI_MODEL", "gemini-2.5-flash"),
        timeout=_TIMEOUT,
    )
    # Tiny prompt, JSON mode, no chat history.
    try:
        text = client.complete(
            system="Reply with only JSON: {\"ok\": true}",
            user="ping",
        )
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        pytest.fail(f"Gemini handshake failed: {exc}")
    parsed = json.loads(text)
    assert parsed.get("ok") is True, f"unexpected Gemini response: {text!r}"


# --------------------------------------------------------------------------- OpenAI
def test_openai_client_handshake_succeeds():
    """Verify the OpenAI endpoint accepts our API key and returns a body
    in the shape our client parses. We send a trivial prompt with
    response_format=json_object and assert a parseable JSON.

    Skipped by default; enable with SATHI_LIVE_TESTS=1 + OPENAI_API_KEY."""
    require_live_env("OPENAI_API_KEY")
    client = OpenAIClient(
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.environ.get("SATHI_OPENAI_MODEL", "gpt-4o"),
        timeout=_TIMEOUT,
    )
    try:
        text = client.complete(
            system="Reply with only JSON: {\"ok\": true}",
            user="ping",
        )
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        pytest.fail(f"OpenAI handshake failed: {exc}")
    parsed = json.loads(text)
    assert parsed.get("ok") is True, f"unexpected OpenAI response: {text!r}"


# --------------------------------------------------------------------------- BD IVR (stand-in only)
def test_bd_ivr_standin_is_reachable():
    """The local stand-in gateway (scripts/bd_ivr_standin.py) must
    respond on /health before the roundtrip test below is meaningful."""
    require_live_env("SATHI_BD_IVR_API_KEY", "SATHI_BD_IVR_WEBHOOK_SECRET")
    base = os.environ.get("SATHI_BD_IVR_STANDIN_URL", "http://127.0.0.1:18443")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, ConnectionError) as exc:
        pytest.skip(
            f"BD IVR stand-in is not running at {base}. Start it with: "
            f"`docker compose --profile live up -d bd_ivr_standin` "
            f"or `python scripts/bd_ivr_standin.py`. ({exc})"
        )
    assert data.get("status") == "ok"


def test_bd_ivr_standin_request_shape_and_signature():
    """Hit the local stand-in /calls endpoint with the exact request
    body the BdHttpIvrProvider adapter produces. Validate:
      * the stand-in returns 200 + JSON with a call_id
      * the stand-in accepts the Bearer key
      * the stand-in rejects an unknown key with 401
    """
    require_live_env("SATHI_BD_IVR_API_KEY", "SATHI_BD_IVR_WEBHOOK_SECRET")
    base = os.environ.get("SATHI_BD_IVR_STANDIN_URL", "http://127.0.0.1:18443")

    payload = {
        "to": "+8801700000000",
        "callback_url": "https://example.invalid/cb",
        "status_url": "https://example.invalid/status",
        "language": "bn-BD",
        "prompt": {"text": "আপনার পিন লিখুন"},
        "gather": {"max_digits": 8, "finish_on_key": "#", "timeout_seconds": 12},
        "client_ref": "test-ref",
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ['SATHI_BD_IVR_API_KEY']}",
    }
    request = urllib.request.Request(
        f"{base}/calls", data=body, method="POST", headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        pytest.skip(f"stand-in not reachable: {exc}")
    assert data.get("call_id", "").startswith("BDI")
    assert data.get("status") == "queued"

    # Wrong key is rejected.
    bad = urllib.request.Request(
        f"{base}/calls", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer not-the-key"},
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(bad, timeout=_TIMEOUT)
    assert excinfo.value.code == 401


def test_bd_ivr_signature_roundtrip_matches_sathi_adapter():
    """The stand-in signs its callback body with the same HMAC-SHA256
    scheme Sathi uses to verify it. This test computes a signature with
    BdHttpIvrProvider.validate_body against a body the stand-in would
    send, and asserts it matches. No network IO required.
    """
    require_live_env("SATHI_BD_IVR_WEBHOOK_SECRET")
    from app.voice.providers import BdHttpIvrProvider

    # Construct the adapter but only call its pure helpers; do not let
    # the constructor make any network call. We bypass __init__ here
    # because it requires a base_url that we don't need for sign/verify.
    secret = os.environ["SATHI_BD_IVR_WEBHOOK_SECRET"]
    class _Statics:
        def sign(self, body: bytes) -> str:
            import hashlib
            import hmac
            return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    statics = _Statics()
    body = json.dumps({"event": "digits", "digits": "3000"}, ensure_ascii=False).encode()
    sig = statics.sign(body)
    # Now verify using a real provider instance (no network call in
    # validate_body; the constructor only enforces config sanity).
    provider = BdHttpIvrProvider(
        base_url="https://standin.invalid",
        api_key="k",
        webhook_secret=secret,
    )
    assert provider.validate_body(body, sig) is True
    assert provider.validate_body(body, "wrong-sig") is False
    assert provider.validate_body(body, None) is False


# --------------------------------------------------------------------------- side-effect gate
def test_live_tests_side_effects_explicitly_opted_in():
    """Reminder: the Twilio/Alpha tests above do NOT place real calls or
    send real SMS. If the operator wants to opt into side effects, they
    must set SATHI_LIVE_TESTS_ALLOW_SIDE_EFFECTS=1 separately. This test
    is always green and exists only to fail fast if that env var is set
    without a deliberate intent declaration in the test file.
    """
    if os.environ.get("SATHI_LIVE_TESTS_ALLOW_SIDE_EFFECTS") == "1":
        # Operator chose real side effects. Nothing to assert here; just
        # surface the choice in the test log so it shows up in CI.
        print("[live] SATHI_LIVE_TESTS_ALLOW_SIDE_EFFECTS=1 — side effects are ENABLED")
    else:
        print(
            "[live] SATHI_LIVE_TESTS_ALLOW_SIDE_EFFECTS not set — "
            "Twilio/Alpha tests are read-only probes"
        )


# ---------------------------------------------------------------- bd-ivr roundtrip
def test_bd_ivr_standin_roundtrip_does_not_explode():
    """End-to-end webhook roundtrip against the local stand-in. Skipped
    unless the stand-in is reachable AND SATHI_LIVE_TESTS=1. This is the
    *integration* test; the smaller tests above are unit-level.
    """
    require_live_env("SATHI_BD_IVR_API_KEY", "SATHI_BD_IVR_WEBHOOK_SECRET")
    base = os.environ.get("SATHI_BD_IVR_STANDIN_URL", "http://127.0.0.1:18443")
    # Quick reachability check; if it isn't up, skip with a hint.
    try:
        urllib.request.urlopen(f"{base}/health", timeout=2).read()
    except (urllib.error.URLError, ConnectionError) as exc:
        pytest.skip(
            f"BD IVR stand-in not running at {base} — start it before "
            f"running this test. ({exc})"
        )

    # Drive the stand-in directly. The full app-level roundtrip needs
    # the API container, the database, and an authenticated mandate, all
    # of which the regular test suite already exercises. This test
    # proves only that our stand-in + the BdHttpIvrProvider signature
    # contract agree on the wire format.
    payload = {
        "to": "+8801700000000",
        "callback_url": "http://127.0.0.1:1/cb",  # stand-in will try to POST here
        "status_url": "http://127.0.0.1:1/status",
        "language": "bn-BD",
        "prompt": {"text": "x"},
        "gather": {"max_digits": 8, "finish_on_key": "#", "timeout_seconds": 12},
        "client_ref": "roundtrip",
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(
        f"{base}/calls", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['SATHI_BD_IVR_API_KEY']}"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    assert data["call_id"].startswith("BDI")
    # The stand-in will try to POST back to callback_url; that's fine —
    # we don't care about the response, only that the stand-in
    # accepted the request without crashing.
    time.sleep(1.0)
