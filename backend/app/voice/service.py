"""Live verification call workflow shared by real (Twilio) and simulated calls.

Security properties:
- The phone number comes only from the server-side phone book, never from the agent.
- The prompt never speaks the requested amount; the customer states it independently.
- Each call has a random URL token (stored as SHA-256) and Twilio webhooks also need a
  valid X-Twilio-Signature.
- Silent duress: an amount typed with a leading 0 (for example 03000) is handled exactly
  like any other answer on the phone, but the mandate is held and an analyst case opens.
- The customer hears the same closing sentence for confirm, refusal, final mismatch and
  duress, so a person standing next to them cannot learn the outcome from the call.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from app.accounts.service import registered_number
from app.mandates.service import MandateError, MandateService
from app.verification.keypad import KeypadParseError
from app.voice import scripts, twiml
from app.voice.providers import VoiceProvider, VoiceProviderError

LIVE_STATUSES = ("queued", "ringing", "in_progress")
# Errors raised while placing a call that mean "the customer was not reached yet".
PLACEMENT_FAILURES = ("VOICE_PROVIDER_ERROR", "VOICE_PROVIDER_UNCERTAIN", "NO_REGISTERED_PHONE",
                      "VOICE_NOT_CONFIGURED")
PROVIDER_STATUS_MAP = {
    "queued": "queued",
    "initiated": "queued",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "answered": "in_progress",
    "no-answer": "no_answer",
    "busy": "no_answer",
    "failed": "failed",
    "canceled": "failed",
}


class VoiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class DigitResult:
    call_status: str
    twiml: str
    spoken: list[str]
    mandate_status: str | None


def mask_number(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        return "registered phone"
    return f"+{digits[:3]}{'•' * max(0, len(digits) - 6)}{digits[-3:]}"


def load_phone_book(env: dict[str, str] | None = None) -> dict[str, str]:
    env = env if env is not None else dict(os.environ)
    raw = env.get("SATHI_VOICE_PHONE_BOOK", "").strip()
    if not raw:
        return {}
    try:
        book = json.loads(raw)
    except ValueError:
        return {}
    return {
        str(user): str(number)
        for user, number in book.items()
        if re.fullmatch(r"\+[1-9]\d{7,14}", str(number))
    }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class VoiceService:
    def __init__(
        self,
        mandate_service: MandateService,
        provider: VoiceProvider,
        public_base_url: str = "",
        phone_book: dict[str, str] | None = None,
    ) -> None:
        self.mandates = mandate_service
        self.provider = provider
        self.public_base_url = public_base_url.rstrip("/")
        self.phone_book = phone_book or {}

    # ---------------------------------------------------------------- placing calls
    def start_call(self, mandate_id: str, agent_id: str) -> dict[str, Any]:
        record = self.mandates.mandates.get(mandate_id)
        if record is None:
            raise VoiceError("MANDATE_NOT_FOUND", f"Mandate {mandate_id} not found", 404)
        if record.agent_id != agent_id:
            raise VoiceError("FORBIDDEN_OWNERSHIP", "Agent does not own this mandate.", 403)
        if record.status != "requested":
            raise VoiceError(
                "INVALID_STATE", f"Calls are only placed for requested mandates ({record.status}).",
                409,
            )

        return self._place_call(record.user_id, agent_id, "mandate_id", mandate_id, "mandate")

    def start_check_call(self, check_id: int, actor: str,
                         automatic: bool = True) -> dict[str, Any]:
        """Call the customer after a completed cash-out to confirm the amount."""
        from app.txn.service import OPEN_STATUSES, TxnCheckService

        checks = TxnCheckService(self.mandates)
        check = checks.get(check_id)
        if check is None:
            raise VoiceError("CHECK_NOT_FOUND", "Transaction check not found.", 404)
        if check["status"] not in OPEN_STATUSES:
            raise VoiceError("CHECK_CLOSED", "This transaction is already confirmed.", 409)
        try:
            call = self._place_call(check["user_id"], actor, "check_id", check_id, "transaction")
        except VoiceError as err:
            checks.set_error(check_id, err.message)
            if err.code in PLACEMENT_FAILURES:
                # The cash-out is already committed. Never strand it: schedule a bounded retry,
                # or hand it to a person once the attempts are used up. No money moves.
                from app.callcenter.service import CallCenterService

                CallCenterService(self.mandates).on_placement_failed(
                    check_id, err.code, err.message, automatic=automatic,
                    uncertain=err.code == "VOICE_PROVIDER_UNCERTAIN")
            raise
        checks.set_calling(check_id)
        from app.callcenter.service import CallCenterService

        CallCenterService(self.mandates).on_call_placed(check_id, automatic=automatic)
        return call

    def _place_call(self, user_id: str, actor: str, target_col: str, target_id: Any,
                    entity: str) -> dict[str, Any]:
        if self.provider.name != "simulated":
            number = self.phone_book.get(user_id) or registered_number(
                self.mandates.get_connection, user_id)
            if not number:
                raise VoiceError(
                    "NO_REGISTERED_PHONE",
                    "Customer has no registered phone number on the server.", 422,
                )
            if not self.public_base_url.startswith("https://"):
                raise VoiceError(
                    "VOICE_NOT_CONFIGURED", "Public HTTPS API URL is not configured.", 503,
                )
            to_masked = mask_number(number)
        else:
            number = ""
            to_masked = "simulated handset"
        assert target_col in ("mandate_id", "check_id")

        call_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(24)
        from app.lang.detect import LanguagePrefs

        language = LanguagePrefs(self.mandates.get_connection).get(user_id)
        conn = self.mandates.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT 1 FROM voice_calls WHERE {target_col} = %s "
                        f"AND status IN {LIVE_STATUSES} FOR UPDATE;",
                        (target_id,),
                    )
                    if cur.fetchone():
                        raise VoiceError(
                            "CALL_IN_PROGRESS", "A verification call is already in progress.", 409,
                        )
                    cur.execute(
                        f"""
                        INSERT INTO voice_calls (
                            call_id, {target_col}, user_id, provider, to_masked, token_hash,
                            status, language
                        ) VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s);
                        """,
                        (call_id, target_id, user_id, self.provider.name, to_masked,
                         _hash_token(token), language),
                    )
        finally:
            conn.close()

        if self.provider.name == "bd_http_ivr":
            events = f"{self.public_base_url}/api/v1/voice/ivr/{call_id}/events?t={token}"
            answer_url, status_url = events, events
        else:
            base = f"{self.public_base_url}/api/v1/voice/calls/{call_id}"
            answer_url, status_url = f"{base}/answer?t={token}", f"{base}/status?t={token}"
        try:
            placed = self.provider.place_call(number, answer_url, status_url)
        except VoiceProviderError as exc:
            if exc.ambiguous:
                # The provider may have accepted the call. Keep the row live so the unique
                # live-call guard blocks a duplicate; its status webhook (or the ring timeout
                # worker) settles it and schedules any retry.
                self.mandates.log_audit(actor, "voice_call_uncertain", entity, str(target_id),
                                        {"call_id": call_id, "reason": str(exc)})
                raise VoiceError("VOICE_PROVIDER_UNCERTAIN", str(exc), 502) from None
            self._set_status(call_id, "failed")
            self.mandates.log_audit(actor, "voice_call_failed", entity, str(target_id),
                                    {"call_id": call_id, "reason": str(exc)})
            raise VoiceError("VOICE_PROVIDER_ERROR", str(exc), 502) from None
        except Exception as exc:  # a provider library bug must not leave a live ghost call
            self._set_status(call_id, "failed")
            self.mandates.log_audit(actor, "voice_call_failed", entity, str(target_id),
                                    {"call_id": call_id, "reason": type(exc).__name__})
            raise VoiceError("VOICE_PROVIDER_ERROR", "The call provider failed.", 502) from None

        self._set_status(call_id, placed.status, provider_call_sid=placed.provider_call_sid)
        self.mandates.log_audit(actor, "voice_call_placed", entity, str(target_id),
                                {"call_id": call_id, "provider": self.provider.name,
                                 "to": to_masked})
        return self.get_call(call_id)

    # ---------------------------------------------------------------- reading calls
    def get_call(self, call_id: str) -> dict[str, Any]:
        row = self._fetch("WHERE call_id = %s", (call_id,))
        if row is None:
            raise VoiceError("CALL_NOT_FOUND", "Call not found.", 404)
        return row

    def latest_for_mandate(self, mandate_id: str) -> dict[str, Any] | None:
        return self._fetch("WHERE mandate_id = %s ORDER BY created_at DESC LIMIT 1", (mandate_id,))

    def incoming_for_user(self, user_id: str) -> list[dict[str, Any]]:
        conn = self.mandates.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT v.call_id, v.mandate_id, COALESCE(m.agent_id, c.agent_id), v.status,
                           v.created_at, v.check_id, v.language
                    FROM voice_calls v
                    LEFT JOIN mandates m ON m.mandate_id = v.mandate_id
                    LEFT JOIN txn_checks c ON c.check_id = v.check_id
                    WHERE v.user_id = %s AND v.provider = 'simulated'
                      AND v.status IN {LIVE_STATUSES}
                    ORDER BY v.created_at DESC;
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [
            {"call_id": str(r[0]), "mandate_id": str(r[1]) if r[1] else None,
             "check_id": r[5], "kind": "transaction" if r[5] else "request",
             "agent_id": r[2], "status": r[3], "created_at": r[4].isoformat(),
             "prompt_bn": twiml.CHECK_PROMPT if r[5] else twiml.PROMPT,
             "language": r[6],
             "prompt": scripts.line(r[6], "check_prompt" if r[5] else "mandate_prompt")}
            for r in rows
        ]

    def _fetch(self, where: str, params: tuple) -> dict[str, Any] | None:
        conn = self.mandates.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT call_id, mandate_id, user_id, provider, to_masked, status, "
                    "digit_attempts, created_at, updated_at, check_id, language, no_input_count "
                    f"FROM voice_calls {where};",
                    params,
                )
                r = cur.fetchone()
        finally:
            conn.close()
        if not r:
            return None
        return {
            "call_id": str(r[0]), "mandate_id": str(r[1]) if r[1] else None,
            "check_id": r[9], "user_id": r[2], "provider": r[3],
            "to": r[4], "status": r[5], "digit_attempts": r[6],
            "created_at": r[7].isoformat(), "updated_at": r[8].isoformat(),
            "language": r[10], "no_input_count": r[11],
        }

    # ---------------------------------------------------------------- authentication
    def check_token(self, call_id: str, token: str | None) -> dict[str, Any]:
        conn = self.mandates.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT token_hash FROM voice_calls WHERE call_id = %s;", (call_id,))
                row = cur.fetchone()
        finally:
            conn.close()
        if not row or not token or not hmac.compare_digest(row[0], _hash_token(token)):
            raise VoiceError("INVALID_CALL_TOKEN", "Unknown call or token.", 403)
        return self.get_call(call_id)

    # ---------------------------------------------------------------- call events
    def mark_answered(self, call_id: str) -> bool:
        """Provider-neutral answer: True when the prompt should be played."""
        call = self.get_call(call_id)
        if call["status"] not in LIVE_STATUSES:
            return False
        self._set_status(call_id, "in_progress")
        return True

    @staticmethod
    def prompt_for(call: dict[str, Any]) -> str:
        return scripts.line(call.get("language"), scripts.prompt_key(call))

    def answer(self, call_id: str, gather_url: str) -> str:
        call = self.get_call(call_id)
        if call["status"] not in LIVE_STATUSES:
            return twiml.close(call.get("language", "bn"))
        self._set_status(call_id, "in_progress")
        return twiml.gather(gather_url, self.prompt_for(call), speech=bool(call.get("check_id")),
                            language=call.get("language", "bn"))

    def provider_status(self, call_id: str, provider_status: str) -> dict[str, Any]:
        call = self.get_call(call_id)
        mapped = PROVIDER_STATUS_MAP.get(provider_status)
        if provider_status == "completed":
            if call["status"] in LIVE_STATUSES:
                # Hung up before answering the prompt.
                self._set_status(call_id, "no_answer")
                self._no_answer(call)
            return self.get_call(call_id)
        if mapped and call["status"] in LIVE_STATUSES:
            self._set_status(call_id, mapped)
            if mapped == "no_answer":
                self._no_answer(call)
        return self.get_call(call_id)

    def handle_digits(self, call_id: str, digits: str | None, gather_url: str,
                      speech: Any = None, confidence: Any = None,
                      no_input: bool = False) -> DigitResult:
        """Apply one customer answer. `no_input` means the gather timed out in silence,
        which is never treated as "I did not do this"."""
        call = self.get_call(call_id)
        lang = call.get("language", "bn")
        if call["status"] not in LIVE_STATUSES:
            return DigitResult(call["status"], twiml.close(lang), [scripts.line(lang, "close")],
                               None)
        # Provider payloads are untrusted: keep non-text values out of persistence and the
        # language learner. A wrong type is an unreadable answer ("unclear"), not silence.
        invalid_input = (not isinstance(digits, (str, type(None)))
                         or not isinstance(speech, (str, type(None))))
        if not isinstance(digits, (str, type(None))):
            digits = None
        has_speech = speech is not None and (not isinstance(speech, str) or bool(speech.strip()))
        speech_text = speech if isinstance(speech, str) else None
        raw = (digits or "").strip()
        digits = re.sub(r"[^0-9]", "", digits or "")
        mandate_id, user_id = call["mandate_id"], call["user_id"]
        attempts = call["digit_attempts"] + 1
        self._set_status(call_id, "in_progress", digit_attempts=attempts)

        if call.get("check_id"):
            if no_input and not has_speech:
                return self._no_input(call, gather_url)
            special = self._check_keys(call, raw, speech_text, gather_url)
            if special is not None:
                return special
            return self._check_digits(call_id, call["check_id"], raw[:12], gather_url,
                                      speech=speech_text, confidence=confidence, language=lang,
                                      invalid_input=invalid_input)

        if digits == "":
            status = self._reject(
                mandate_id, user_id, "customer_denied_request",
                {"channel": "voice", "call_id": call_id},
            )
            self._set_status(call_id, "rejected")
            return DigitResult("rejected", twiml.close(lang), [scripts.line(lang, "close")], status)

        if len(digits) > 1 and digits.startswith("0"):
            record = self.mandates.mandates.get(mandate_id)
            stated = int(digits)
            status = self._reject(
                mandate_id, user_id, "duress_signal",
                {
                    "channel": "voice", "call_id": call_id, "priority": "urgent",
                    "stated_amount": stated,
                    "amount_matched": bool(record and abs(record.amount - stated) < 0.01),
                    "guidance": "Customer used the silent duress signal. Contact the customer "
                    "on the registered number away from the agent before any further action.",
                },
            )
            self._set_status(call_id, "duress")
            return DigitResult("duress", twiml.close(lang), [scripts.line(lang, "close")], status)

        try:
            result = self.mandates.verify_mandate(
                mandate_id=mandate_id, mode="voice", stated_amount=digits, actor=user_id,
            )
        except (MandateError, KeypadParseError):
            self._set_status(call_id, "failed")
            return DigitResult("failed", twiml.close(lang), [scripts.line(lang, "close")], None)

        if result["outcome"] == "match":
            self._set_status(call_id, "verified")
            return DigitResult("verified", twiml.close(lang), [scripts.line(lang, "close")],
                               "verified")
        if result["status"] == "requested":
            return DigitResult(
                "in_progress", twiml.gather(gather_url, scripts.line(lang, "mandate_retry"),
                                            language=lang),
                [scripts.line(lang, "mandate_retry")], "requested"
            )
        self._set_status(call_id, "mismatch")
        return DigitResult("mismatch", twiml.close(lang), [scripts.line(lang, "close")],
                           result["status"])

    def _no_input(self, call: dict[str, Any], gather_url: str) -> DigitResult:
        """Silence: ask once more kindly, then end and let the scheduler retry later."""
        from app.callcenter.service import CallCenterService

        lang = call.get("language", "bn")
        count = call.get("no_input_count", 0) + 1
        self._bump_no_input(call["call_id"], count)
        CallCenterService(self.mandates).record_response(
            call["check_id"], "no_input", call_id=call["call_id"])
        if count < 2:
            return DigitResult("in_progress",
                               twiml.gather(gather_url, scripts.line(lang, "no_input"),
                                            speech=True, language=lang),
                               [scripts.line(lang, "no_input")], None)
        self._set_status(call["call_id"], "no_answer")
        self._no_answer(call)
        text = scripts.line(lang, "goodbye_no_input")
        return DigitResult("no_answer", twiml.close(lang, text), [text], "no_answer")

    def _check_keys(self, call: dict[str, Any], raw: str, speech: str | None,
                    gather_url: str) -> DigitResult | None:
        """Key 9: talk to a person. Key 8: switch language. Speech teaches the language."""
        from app.callcenter.service import CallCenterService
        from app.lang.detect import LanguagePrefs

        prefs = LanguagePrefs(self.mandates.get_connection)
        if (speech or "").strip():
            prefs.learn(call["user_id"], speech, "speech")
        keys = raw.replace("#", "")
        lang = call.get("language", "bn")
        center = CallCenterService(self.mandates)
        if keys == "9":
            center.record_response(call["check_id"], "human_requested", call_id=call["call_id"],
                                   raw=raw)
            center.request_human(call["check_id"], "customer_requested_human")
            self._set_status(call["call_id"], "completed")
            text = scripts.line(lang, "handoff")
            return DigitResult("completed", twiml.close(lang, text), [text], "manual_review")
        if keys == "8":
            new = scripts.NEXT_LANGUAGE[scripts.normalize(lang)]
            self._set_language(call["call_id"], new)
            prefs.set(call["user_id"], new, "call_keypad")
            center.record_response(call["check_id"], "language_switch", call_id=call["call_id"],
                                   raw=new)
            prompt = scripts.line(new, "check_prompt")
            return DigitResult("in_progress",
                               twiml.gather(gather_url, prompt, speech=True, language=new),
                               [prompt], None)
        return None

    def _check_digits(self, call_id: str, check_id: int, raw: str, gather_url: str,
                      speech: str | None = None, confidence: Any = None,
                      language: str = "bn", invalid_input: bool = False) -> DigitResult:
        from app.callcenter.interpret import Answer, interpret
        from app.callcenter.service import CallCenterService
        from app.txn.service import TxnCheckService

        checks = TxnCheckService(self.mandates)
        center = CallCenterService(self.mandates)
        answer = (Answer("unclear", reason="invalid_input") if invalid_input else
                  interpret(raw, speech, confidence,
                            min_confidence=center.policy()["unclear_confidence"]))
        if answer.kind == "unclear":
            result = checks.handle_unclear(check_id)
            center.on_unclear(check_id, call_id, answer.raw, answer.confidence,
                              final=result != "retry", reason=answer.reason)
            if result == "retry":
                text = scripts.line(language, "unclear")
                return DigitResult("in_progress",
                                   twiml.gather(gather_url, text, speech=True, language=language),
                                   [text], None)
            self._set_status(call_id, "unclear")
            return DigitResult("unclear", twiml.close(language),
                               [scripts.line(language, "close")], result)

        digits = answer.digits if answer.kind == "amount" else ""
        result = checks.handle_answer(check_id, digits)
        interpreted = "denied" if answer.kind == "denied" else (
            "duress" if len(digits) > 1 and digits.startswith("0") else "amount")
        center.record_response(check_id, interpreted, call_id=call_id, raw=answer.raw,
                               amount=int(digits) if digits else None,
                               confidence=answer.confidence)
        if result == "retry":
            text = scripts.line(language, "retry")
            return DigitResult("in_progress",
                               twiml.gather(gather_url, text, speech=True, language=language),
                               [text], None)
        check = checks.get(check_id) or {}
        center.on_resolved(check_id, check.get("status", ""))
        call_status = {"match": "verified", "mismatch": "mismatch", "denied": "rejected",
                       "duress": "duress"}.get(check.get("outcome"), "failed")
        self._set_status(call_id, call_status)
        return DigitResult(call_status, twiml.close(language), [scripts.line(language, "close")],
                           check.get("status"))

    # ---------------------------------------------------------------- persistence helpers
    def _set_language(self, call_id: str, language: str) -> None:
        with self.mandates.get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE voice_calls SET language = %s, updated_at = now() "
                        "WHERE call_id = %s;", (language, call_id))
            conn.commit()

    def _bump_no_input(self, call_id: str, count: int) -> None:
        with self.mandates.get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE voice_calls SET no_input_count = %s, updated_at = now() "
                        "WHERE call_id = %s;", (count, call_id))
            conn.commit()

    def _set_status(self, call_id: str, status: str, provider_call_sid: str | None = None,
                    digit_attempts: int | None = None) -> None:
        conn = self.mandates.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE voice_calls SET status = %s,
                            provider_call_sid = COALESCE(%s, provider_call_sid),
                            digit_attempts = COALESCE(%s, digit_attempts),
                            updated_at = now()
                        WHERE call_id = %s;
                        """,
                        (status, provider_call_sid, digit_attempts, call_id),
                    )
        finally:
            conn.close()

    def _no_answer(self, call: dict[str, Any]) -> None:
        if call.get("check_id"):
            from app.callcenter.service import CallCenterService
            from app.txn.service import TxnCheckService

            TxnCheckService(self.mandates).set_no_answer(call["check_id"])
            CallCenterService(self.mandates).on_no_answer(call["check_id"], call["call_id"])
        else:
            self._record_no_answer(call["mandate_id"])

    def _record_no_answer(self, mandate_id: str) -> None:
        conn = self.mandates.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO verification_events (mandate_id, mode, outcome, ts) "
                        "VALUES (%s, 'voice', 'no_answer', now());",
                        (mandate_id,),
                    )
        finally:
            conn.close()

    def _reject(self, mandate_id: str, user_id: str, reason: str,
                evidence: dict[str, Any]) -> str:
        """Hold a requested mandate. The agent sees the same 'rejected' state for every reason."""
        conn = self.mandates.get_connection()
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status, agent_id FROM mandates WHERE mandate_id = %s FOR UPDATE;",
                        (mandate_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return "missing"
                    status, agent_id = row
                    if status == "requested":
                        cur.execute(
                            "UPDATE mandates SET status = 'rejected' WHERE mandate_id = %s;",
                            (mandate_id,),
                        )
                        status = "rejected"
                    cur.execute(
                        """
                        INSERT INTO cases (
                            mandate_id, agent_id, reason, evidence, status, created_at
                        )
                        VALUES (%s, %s, %s, %s::jsonb, 'open', now());
                        """,
                        (mandate_id, agent_id, reason, json.dumps(evidence)),
                    )
                    cur.execute(
                        """
                        INSERT INTO audit_log (
                            actor, action, entity, entity_id, policy_version, detail, ts
                        ) VALUES (%s, %s, 'mandate', %s, 'v1.0', %s::jsonb, %s);
                        """,
                        (user_id, f"voice_{reason}", mandate_id,
                         json.dumps({"channel": "voice"}),
                         datetime.datetime.now(datetime.timezone.utc)),
                    )
            return status
        finally:
            conn.close()
