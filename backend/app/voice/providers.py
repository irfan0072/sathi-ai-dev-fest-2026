"""Outbound call providers for the live verification channel.

`TwilioVoiceProvider` uses the Twilio REST API over HTTPS with the standard library only.
`SimulatedVoiceProvider` places no real call; the customer console answers instead, and the
answer goes through exactly the same digit-handling code as a real call.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("sathi.voice")


class VoiceProviderError(RuntimeError):
    """Provider could not place the call. Message never contains credentials."""


@dataclass
class PlacedCall:
    provider_call_sid: str
    status: str


class VoiceProvider(Protocol):
    name: str

    def place_call(self, to_number: str, answer_url: str, status_url: str) -> PlacedCall: ...

    def validate_request(self, url: str, params: dict[str, str], signature: str | None) -> bool: ...


class SimulatedVoiceProvider:
    name = "simulated"

    def place_call(self, to_number: str, answer_url: str, status_url: str) -> PlacedCall:
        return PlacedCall(provider_call_sid=f"SIM{secrets.token_hex(8)}", status="ringing")

    def validate_request(self, url: str, params: dict[str, str], signature: str | None) -> bool:
        # Simulated calls never arrive as provider webhooks.
        return False


def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Compute Twilio's X-Twilio-Signature: base64(HMAC-SHA1(url + sorted key/value pairs))."""
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


# Twilio error codes seen when placing a call, with the fix in plain words.
TWILIO_FIXES = {
    21219: "This phone is not verified on your trial account. In the Twilio Console open "
           "Phone Numbers > Manage > Verified Caller IDs and add it (+8801XXXXXXXXX).",
    21215: "Calls to this country are blocked. In the Twilio Console open Voice > Settings > "
           "Geo permissions and tick Bangladesh, then save.",
    13227: "Calls to this country are blocked. In the Twilio Console open Voice > Settings > "
           "Geo permissions and tick Bangladesh, then save.",
    21210: "The From number is not one of your Twilio numbers. Set TWILIO_FROM_NUMBER to the "
           "number in Phone Numbers > Manage > Active numbers (+1XXXXXXXXXX).",
    21212: "The From number is not valid. Use your Twilio number in +1XXXXXXXXXX form.",
    21211: "The phone number is not valid. Use +8801XXXXXXXXX (13 digits after +).",
    21214: "This phone number cannot receive calls. Try another number.",
    21216: "Calls to this number are blocked by Twilio. Try another number.",
    20003: "Twilio rejected the Account SID or Auth Token. Copy both again from Account Info.",
    20404: "Account SID not found. Copy it again from Account Info in the Twilio Console.",
}


def twilio_error(exc: urllib.error.HTTPError) -> str:
    """Twilio's own error code and message, plus the fix when we know it."""
    code, message, raw = None, "", ""
    try:
        raw = (exc.read() or b"").decode("utf-8", "replace")
    except Exception as read_error:  # body already consumed or connection dropped
        raw = f"<unreadable: {type(read_error).__name__}>"
    try:
        data = json.loads(raw or "{}")
        code, message = data.get("code"), str(data.get("message") or "")
    except ValueError:
        pass
    if isinstance(code, str) and code.isdigit():
        code = int(code)
    log.warning("twilio HTTP %s: %s", exc.code, raw[:500])
    if "trial accounts have limited parameter access" in message.lower():
        # Newer Twilio trials accept only "to" plus Twilio's sample call scripts, so no
        # app can play its own voice prompt or read the keypad answer.
        return ("Twilio trial accounts only allow Twilio's sample call scripts, so Sathi's "
                "own Bangla prompt and keypad answer cannot run. Upgrade the Twilio account "
                "(Console > Billing > Upgrade, add credit) and test again, or use the "
                "simulated handset or the Bangladesh IVR provider for the demo.")
    fix = TWILIO_FIXES.get(code) if isinstance(code, int) else None
    if code:
        head = f"Twilio error {code}: {message}".strip()
    else:
        snippet = " ".join(raw.split())[:200]
        head = f"Twilio rejected the call (HTTP {exc.code})." + (
            f" Twilio said: {snippet}" if snippet else " Twilio sent no details.")
    return f"{head} {fix}" if fix else head


class TwilioVoiceProvider:
    name = "twilio"
    api_base = "https://api.twilio.com/2010-04-01"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout_seconds: float = 10.0,
        opener=urllib.request.urlopen,
    ) -> None:
        if not (account_sid and auth_token and from_number):
            raise VoiceProviderError("Twilio credentials are not configured.")
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._timeout = timeout_seconds
        self._open = opener

    def place_call(self, to_number: str, answer_url: str, status_url: str) -> PlacedCall:
        body = urllib.parse.urlencode(
            [
                ("To", to_number),
                ("From", self._from),
                ("Url", answer_url),
                ("Method", "POST"),
                ("StatusCallback", status_url),
                ("StatusCallbackMethod", "POST"),
                ("StatusCallbackEvent", "initiated"),
                ("StatusCallbackEvent", "ringing"),
                ("StatusCallbackEvent", "answered"),
                ("StatusCallbackEvent", "completed"),
                ("Timeout", "30"),
            ]
        ).encode()
        auth = base64.b64encode(f"{self._sid}:{self._token}".encode()).decode()
        request = urllib.request.Request(
            f"{self.api_base}/Accounts/{urllib.parse.quote(self._sid)}/Calls.json",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with self._open(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raise VoiceProviderError(twilio_error(exc)) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise VoiceProviderError("Twilio is unreachable.") from None
        sid = data.get("sid")
        if not sid:
            raise VoiceProviderError("Twilio response did not include a call SID.")
        return PlacedCall(provider_call_sid=str(sid), status="queued")

    def validate_request(self, url: str, params: dict[str, str], signature: str | None) -> bool:
        if not signature:
            return False
        expected = twilio_signature(self._token, url, params)
        return hmac.compare_digest(expected, signature)


class BdHttpIvrProvider:
    """Vendor-neutral JSON IVR adapter for Bangladesh voice gateways.

    Local gateways (for example Infosoftbd's voice API, which advertises outbound calls,
    DTMF capture and webhooks with Bearer auth) do not publish one shared schema, so this
    adapter speaks a small documented contract (docs/live-mode.md) that a vendor or a thin
    relay maps to its own fields:

    - POST {base}/calls with Bearer key and JSON
      {to, callback_url, language, prompt: {text}, gather: {max_digits, finish_on_key,
      timeout_seconds}, client_ref} -> {"call_id": "..."}
    - The gateway POSTs JSON events to callback_url, signed with
      X-Sathi-Signature = hex(HMAC-SHA256(webhook_secret, raw_body)).
    """

    name = "bd_http_ivr"
    signature_header = "X-Sathi-Signature"

    def __init__(self, base_url: str, api_key: str, webhook_secret: str,
                 language: str = "bn-BD", timeout_seconds: float = 10.0,
                 opener=urllib.request.urlopen) -> None:
        if not (base_url.startswith("https://") and api_key and len(webhook_secret) >= 16):
            raise VoiceProviderError("Bangladesh IVR gateway is not configured.")
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._secret = webhook_secret
        self.language = language
        self._timeout = timeout_seconds
        self._open = opener

    def place_call(self, to_number: str, answer_url: str, status_url: str) -> PlacedCall:
        from app.voice import twiml

        payload = {
            "to": to_number,
            "callback_url": answer_url,
            "status_url": status_url,
            "language": self.language,
            "prompt": {"text": twiml.CHECK_PROMPT},
            "gather": {"max_digits": 8, "finish_on_key": "#", "timeout_seconds": 12},
            "client_ref": answer_url.rsplit("/calls/", 1)[-1].split("/", 1)[0],
        }
        request = urllib.request.Request(
            f"{self._base}/calls", data=json.dumps(payload, ensure_ascii=False).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        try:
            with self._open(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            raise VoiceProviderError(f"IVR gateway rejected the call (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise VoiceProviderError("IVR gateway is unreachable.") from None
        call_id = data.get("call_id") or data.get("id")
        if not call_id:
            raise VoiceProviderError("IVR gateway response did not include a call id.")
        return PlacedCall(provider_call_sid=str(call_id), status="queued")

    def sign(self, body: bytes) -> str:
        return hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()

    def validate_body(self, body: bytes, signature: str | None) -> bool:
        return bool(signature) and hmac.compare_digest(self.sign(body), signature)

    def validate_request(self, url: str, params: dict[str, str], signature: str | None) -> bool:
        # Form-encoded Twilio-style webhooks are never accepted for this provider.
        return False


def provider_from_env(env: dict[str, str] | None = None) -> VoiceProvider:
    env = env if env is not None else dict(os.environ)
    choice = env.get("SATHI_VOICE_PROVIDER", "simulated").strip().lower()
    if choice == "twilio":
        return TwilioVoiceProvider(
            env.get("TWILIO_ACCOUNT_SID", ""),
            env.get("TWILIO_AUTH_TOKEN", ""),
            env.get("TWILIO_FROM_NUMBER", ""),
        )
    if choice == "bd_http_ivr":
        return BdHttpIvrProvider(
            env.get("SATHI_BD_IVR_BASE_URL", ""),
            env.get("SATHI_BD_IVR_API_KEY", ""),
            env.get("SATHI_BD_IVR_WEBHOOK_SECRET", ""),
            env.get("SATHI_BD_IVR_LANGUAGE", "bn-BD"),
        )
    if choice == "simulated":
        return SimulatedVoiceProvider()
    raise VoiceProviderError(f"Unknown voice provider '{choice}'.")
