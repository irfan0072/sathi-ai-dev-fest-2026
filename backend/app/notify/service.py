"""SMS notifications: Alpha SMS (sms.net.bd) or a simulated outbox.

Two messages only, both sent AFTER the fact so they never reveal a requested amount
before the customer states it independently:

- `cashout_receipt`: after redemption, the ledger amount and fee, plus "not you?" advice.
- `verification_call_missed`: the verification call was not answered.

Sending is best-effort: a failed SMS is recorded and never blocks or reverses money flow.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from app.voice.service import load_phone_book, mask_number

TEMPLATES = {
    "cashout_receipt": (
        "সাথী: আপনার একাউন্ট থেকে ৳{amount} উত্তোলন হয়েছে (ফি ৳{fee})। "
        "আপনি না করে থাকলে এখনই সাথী হেল্পলাইনে জানান। পিন কাউকে বলবেন না।"
    ),
    "verification_call_missed": (
        "সাথী: একজন এজেন্ট আপনার একাউন্ট থেকে টাকা তোলার অনুরোধ করেছেন। আমরা আপনাকে কল "
        "করেছিলাম। আপনি অনুরোধ না করে থাকলে কিছু করার দরকার নেই।"
    ),
}


@dataclass
class SmsResult:
    status: str
    provider_ref: str | None = None
    error: str | None = None


class SimulatedSmsProvider:
    name = "simulated"

    def send(self, to_number: str, body: str) -> SmsResult:
        return SmsResult("simulated")


class AlphaSmsProvider:
    """Alpha SMS gateway: POST https://api.sms.net.bd/sendsms (api_key, msg, to, sender_id)."""

    name = "alpha_sms"
    endpoint = "https://api.sms.net.bd/sendsms"

    def __init__(self, api_key: str, sender_id: str = "", timeout: float = 10.0,
                 opener: Callable = urllib.request.urlopen) -> None:
        if not api_key:
            raise ValueError("ALPHA_SMS_API_KEY is not configured.")
        self._key, self._sender, self._timeout, self._open = api_key, sender_id, timeout, opener

    def send(self, to_number: str, body: str) -> SmsResult:
        fields = {"api_key": self._key, "msg": body, "to": to_number.lstrip("+")}
        if self._sender:
            fields["sender_id"] = self._sender
        request = urllib.request.Request(
            self.endpoint, data=urllib.parse.urlencode(fields).encode(), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._open(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode() or "{}")
        except (urllib.error.URLError, TimeoutError, ValueError):
            return SmsResult("failed", error="SMS gateway unreachable")
        if data.get("error") == 0:
            ref = str((data.get("data") or {}).get("request_id", "")) or None
            return SmsResult("sent", provider_ref=ref)
        return SmsResult("failed", error=f"Gateway error {data.get('error')}")


def sms_provider_from_env(env: dict[str, str] | None = None) -> Any:
    env = env if env is not None else dict(os.environ)
    if env.get("SATHI_SMS_PROVIDER", "simulated").strip().lower() == "alpha":
        return AlphaSmsProvider(env.get("ALPHA_SMS_API_KEY", ""),
                                env.get("ALPHA_SMS_SENDER_ID", ""))
    return SimulatedSmsProvider()


def _bn_number(value: float) -> str:
    digits = f"{value:,.2f}".rstrip("0").rstrip(".")
    return digits.translate(str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯"))


class NotificationService:
    def __init__(self, get_connection: Callable, provider: Any,
                 phone_book: dict[str, str] | None = None) -> None:
        self._conn = get_connection
        self.provider = provider
        self.phone_book = phone_book if phone_book is not None else load_phone_book()

    def notify(self, user_id: str, template: str, mandate_id: str | None = None,
               **params: float) -> dict[str, Any]:
        body = TEMPLATES[template].format(
            **{k: _bn_number(v) if isinstance(v, (int, float)) else v for k, v in params.items()})
        number = self.phone_book.get(user_id)
        if self.provider.name == "simulated":
            result, to_masked = self.provider.send("", body), "simulated outbox"
        elif not number:
            result, to_masked = SmsResult("skipped", error="No registered phone"), "none"
        else:
            result, to_masked = self.provider.send(number, body), mask_number(number)
        conn = self._conn()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO notifications (
                            user_id, mandate_id, channel, provider, template, to_masked, body,
                            status, provider_ref, error
                        ) VALUES (%s, %s, 'sms', %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (mandate_id, template) WHERE mandate_id IS NOT NULL
                        DO NOTHING
                        RETURNING notification_id, created_at;
                        """,
                        (user_id, mandate_id, self.provider.name, template, to_masked, body,
                         result.status, result.provider_ref, result.error),
                    )
                    row = cur.fetchone()
        finally:
            conn.close()
        return {"notification_id": row[0] if row else None, "status": result.status,
                "duplicate": row is None, "body": body}

    def list_for_user(self, user_id: str | None, limit: int = 30) -> list[dict[str, Any]]:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT notification_id, user_id, mandate_id, provider, template, to_masked, "
                    "body, status, created_at FROM notifications "
                    "WHERE (%s::text IS NULL OR user_id = %s) "
                    "ORDER BY created_at DESC LIMIT %s;",
                    (user_id, user_id, limit),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {"notification_id": r[0], "user_id": r[1],
             "mandate_id": str(r[2]) if r[2] else None, "provider": r[3], "template": r[4],
             "to": r[5], "body": r[6], "status": r[7], "created_at": r[8].isoformat()}
            for r in rows
        ]
