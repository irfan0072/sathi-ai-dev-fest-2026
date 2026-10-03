"""Provider credentials entered from the Settings page.

- Encrypted at rest with Fernet. The key is derived from SATHI_SECRETS_KEY, which lives
  only in the server environment. Without it, credential editing is disabled.
- Write-only: the API returns a hint (last 4 characters for secrets, masked phones), never
  a value. Every change writes an audit row without the value.
- Precedence: a value saved on the Settings page overrides the environment variable of
  the same name. Clearing it falls back to the environment again.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

E164 = r"^\+[1-9]\d{7,14}$"


@dataclass(frozen=True)
class Credential:
    name: str
    provider: str
    label: str
    kind: str  # secret | text | url | phone | phonebook
    help: str
    pattern: str | None = None
    min_length: int = 1
    max_length: int = 512


CREDENTIALS: tuple[Credential, ...] = (
    Credential("TWILIO_ACCOUNT_SID", "twilio", "Account SID", "text",
               "From your Twilio dashboard (starts with AC).", pattern=r"^AC[0-9a-fA-F]{32}$"),
    Credential("TWILIO_AUTH_TOKEN", "twilio", "Auth token", "secret",
               "From your Twilio dashboard, next to the Account SID.",
               pattern=r"^[0-9a-fA-F]{32}$"),
    Credential("TWILIO_FROM_NUMBER", "twilio", "Twilio phone number", "phone",
               "The number that calls customers, with country code, e.g. +12025550123.",
               pattern=E164),
    Credential("SATHI_PUBLIC_API_URL", "webhooks", "Public web address", "url",
               "The internet address of this Sathi server, e.g. https://sathi-api.onrender.com. "
               "Phone services send call results here.",
               pattern=r"^https://[A-Za-z0-9.\-]+(:\d+)?$"),
    Credential("SATHI_BD_IVR_BASE_URL", "bd_ivr", "Provider web address", "url",
               "Given by your Bangladesh phone provider. Must start with https://.",
               pattern=r"^https://[A-Za-z0-9.\-]+(:\d+)?(/[A-Za-z0-9._~\-/]*)?$"),
    Credential("SATHI_BD_IVR_API_KEY", "bd_ivr", "Provider API key", "secret",
               "Given by your Bangladesh phone provider.", min_length=8),
    Credential("SATHI_BD_IVR_WEBHOOK_SECRET", "bd_ivr", "Shared secret", "secret",
               "Press Generate, then give the same value to the provider.", min_length=16),
    Credential("ALPHA_SMS_API_KEY", "alpha_sms", "API key", "secret",
               "From your Alpha SMS account, under API.", min_length=8),
    Credential("ALPHA_SMS_SENDER_ID", "alpha_sms", "Sender name (optional)", "text",
               "The name customers see as the SMS sender, if Alpha approved one.",
               pattern=r"^[A-Za-z0-9 ]{1,15}$|^\d{6,15}$"),
    Credential("GEMINI_API_KEY", "gemini", "API key", "secret",
               "From Google AI Studio, under API keys.", min_length=20),
    Credential("OPENAI_API_KEY", "openai", "API key", "secret",
               "From the OpenAI website, under API keys (starts with sk-).",
               pattern=r"^sk-[A-Za-z0-9_\-]{20,}$"),
    Credential("SATHI_VOICE_PHONE_BOOK", "phone_book", "Customer phone numbers", "phonebook",
               "Confirmation calls go only to these numbers."),
)
BY_NAME = {c.name: c for c in CREDENTIALS}

PROVIDERS = {
    "twilio": "Twilio phone calls",
    "webhooks": "Public web address",
    "bd_ivr": "Bangladesh phone provider",
    "alpha_sms": "Alpha SMS (sms.net.bd)",
    "gemini": "Google Gemini AI",
    "openai": "OpenAI (GPT-4o)",
    "phone_book": "Customer phone numbers",
}


class CredentialError(ValueError):
    def __init__(self, message: str, name: str | None = None):
        super().__init__(message)
        self.name = name


def _mask_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) <= 6:
        return "•••"
    return f"+{digits[:3]}{'•' * (len(digits) - 6)}{digits[-3:]}"


def fernet_from_env(env: dict[str, str]) -> Fernet | None:
    raw = env.get("SATHI_SECRETS_KEY", "").strip()
    if len(raw) < 32 or raw in ("CHANGE_ME",):
        return None
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def validate(cred: Credential, value: Any) -> str:
    if cred.kind == "phonebook":
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise CredentialError("Phone book must be a JSON object.", cred.name) from None
        if not isinstance(value, dict) or len(value) > 500:
            raise CredentialError("Phone book must map customer ids to phones.", cred.name)
        clean = {}
        for user, phone in value.items():
            if not re.fullmatch(r"^[A-Za-z0-9_]{3,64}$", str(user)):
                raise CredentialError(f"Invalid customer id '{user}'.", cred.name)
            if not re.fullmatch(E164, str(phone).strip()):
                raise CredentialError(f"Phone for {user} must be E.164, e.g. +8801XXXXXXXXX.",
                                      cred.name)
            clean[str(user)] = str(phone).strip()
        return json.dumps(clean, sort_keys=True)
    if not isinstance(value, str):
        raise CredentialError("Expected text.", cred.name)
    value = value.strip()
    if cred.kind == "url":
        value = value.rstrip("/")
    if not (cred.min_length <= len(value) <= cred.max_length):
        raise CredentialError(f"Must be {cred.min_length}–{cred.max_length} characters.",
                              cred.name)
    if cred.pattern and not re.fullmatch(cred.pattern, value):
        raise CredentialError("This does not look right. " + cred.help, cred.name)
    if any(ch in value for ch in "\r\n\t"):
        raise CredentialError("Control characters are not allowed.", cred.name)
    return value


def hint_for(cred: Credential, value: str) -> str:
    if cred.kind == "secret":
        return f"••••{value[-4:]}" if len(value) >= 8 else "••••"
    if cred.kind == "phone":
        return _mask_phone(value)
    if cred.kind == "phonebook":
        book = json.loads(value)
        return f"{len(book)} number{'s' if len(book) != 1 else ''}"
    return value


class CredentialStore:
    def __init__(self, get_connection: Callable, env: dict[str, str] | None = None) -> None:
        self._conn = get_connection
        self._base_env = env

    @property
    def base_env(self) -> dict[str, str]:
        return self._base_env if self._base_env is not None else dict(os.environ)

    @property
    def fernet(self) -> Fernet | None:
        return fernet_from_env(self.base_env)

    def _rows(self) -> dict[str, tuple[str, str, str, str]]:
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT name, ciphertext, hint, updated_by, updated_at "
                            "FROM provider_credentials;")
                return {r[0]: (r[1], r[2], r[3], r[4].isoformat()) for r in cur.fetchall()}
        except Exception:
            return {}

    def stored_values(self) -> tuple[dict[str, str], set[str]]:
        """Decrypted values, plus names that could not be decrypted (key changed)."""
        fernet, values, unreadable = self.fernet, {}, set()
        for name, (cipher, _hint, _by, _at) in self._rows().items():
            if name not in BY_NAME:
                continue
            if fernet is None:
                unreadable.add(name)
                continue
            try:
                values[name] = fernet.decrypt(cipher.encode()).decode()
            except InvalidToken:
                unreadable.add(name)
        return values, unreadable

    def effective_env(self) -> dict[str, str]:
        values, _ = self.stored_values()
        return {**self.base_env, **values}

    def status(self) -> dict[str, Any]:
        rows = self._rows()
        _values, unreadable = self.stored_values()
        env = self.base_env
        items = []
        for cred in CREDENTIALS:
            item: dict[str, Any] = {
                "name": cred.name, "provider": cred.provider, "label": cred.label,
                "kind": cred.kind, "help": cred.help,
            }
            if cred.name in rows and cred.name not in unreadable:
                _c, hint, by, at = rows[cred.name]
                item.update(source="settings", hint=hint, updated_by=by, updated_at=at)
            elif cred.name in unreadable:
                item.update(source="unreadable", hint=None,
                            note="The saved value can no longer be read. Please enter it again.")
            elif env.get(cred.name, "").strip():
                raw = env[cred.name].strip()
                try:
                    item.update(source="env", hint=hint_for(cred, validate(cred, raw)))
                except CredentialError:
                    item.update(source="env", hint="set (invalid format)")
            else:
                item.update(source="missing", hint=None)
            if cred.kind == "phonebook" and item["source"] in ("settings", "env"):
                book = json.loads(self.effective_env().get(cred.name) or "{}")
                item["entries"] = [{"user_id": u, "phone": _mask_phone(p)}
                                   for u, p in sorted(book.items())]
            items.append(item)
        return {
            "encryption_ready": self.fernet is not None,
            "providers": [{"id": k, "label": v} for k, v in PROVIDERS.items()],
            "items": items,
        }

    def save(self, values: dict[str, Any], actor: str) -> list[str]:
        fernet = self.fernet
        if fernet is None:
            raise CredentialError("Saving is turned off: the server has no safe-storage key "
                                  "(SATHI_SECRETS_KEY) yet.")
        clean = {}
        for name, value in values.items():
            if name not in BY_NAME:
                raise CredentialError("Unknown credential.", name)
            if value in (None, ""):
                continue
            clean[name] = validate(BY_NAME[name], value)
        if not clean:
            raise CredentialError("No values submitted.")
        with self._conn() as conn:
            with conn.cursor() as cur:
                for name, value in clean.items():
                    cur.execute(
                        """
                        INSERT INTO provider_credentials (name, ciphertext, hint, updated_by)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET ciphertext = EXCLUDED.ciphertext,
                            hint = EXCLUDED.hint, updated_by = EXCLUDED.updated_by,
                            updated_at = now();
                        """,
                        (name, fernet.encrypt(value.encode()).decode(),
                         hint_for(BY_NAME[name], value), actor),
                    )
                cur.execute(
                    "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES (%s, 'credentials_updated', 'credentials', %s, 'v1.0', "
                    "%s::jsonb, now());",
                    (actor, ",".join(sorted(clean)),
                     json.dumps({"names": sorted(clean),
                                 "hints": {n: hint_for(BY_NAME[n], v) for n, v in clean.items()
                                           if BY_NAME[n].kind != "phonebook"}})),
                )
            conn.commit()
        return sorted(clean)

    def clear(self, name: str, actor: str) -> bool:
        if name not in BY_NAME:
            raise CredentialError("Unknown credential.", name)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM provider_credentials WHERE name = %s;", (name,))
                removed = cur.rowcount > 0
                if removed:
                    cur.execute(
                        "INSERT INTO audit_log (actor, action, entity, entity_id, "
                        "policy_version, detail, ts) VALUES (%s, 'credential_cleared', "
                        "'credentials', %s, 'v1.0', '{}'::jsonb, now());",
                        (actor, name),
                    )
            conn.commit()
        return removed


def runtime_env(get_connection: Callable) -> dict[str, str]:
    """Environment for provider construction: env overlaid with Settings-page credentials."""
    return CredentialStore(get_connection).effective_env()


def fingerprint(env: dict[str, str], names: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps([env.get(n, "") for n in names]).encode()).hexdigest()
