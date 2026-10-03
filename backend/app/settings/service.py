"""Runtime operational settings.

Precedence: database override (set by an analyst, audited) > environment variable >
built-in default. Every value has a type and safe bounds checked on write.

Never configurable here:
- Secrets (API keys, tokens, webhook secrets): environment only; reported as
  configured/missing, never returned.
- The customer phone book: changing a registered number from a web page would let an
  attacker route verification calls to themselves. It stays in the environment.
- Ledger policy in data/config.yaml (caps, fees, attempts, TTL): it is hash-locked to the
  verified artifact bundle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.voice.service import load_phone_book, mask_number


class SettingsError(ValueError):
    def __init__(self, message: str, key: str | None = None):
        super().__init__(message)
        self.key = key


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    group: str
    kind: str  # enum | bool | float | int | text
    default: Any
    help: str
    env: str | None = None
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    unit: str = ""
    option_labels: dict[str, str] = field(default_factory=dict)


REGISTRY: tuple[Setting, ...] = (
    Setting("voice.provider", "Who makes the confirmation call", "Calls and messages", "enum",
            "simulated",
            "The service that phones customers to confirm the amount. Real services need their "
            "account details saved below first.",
            env="SATHI_VOICE_PROVIDER", options=("simulated", "twilio", "bd_http_ivr"),
            option_labels={"simulated": "Demo phone (no real call)", "twilio": "Twilio",
                           "bd_http_ivr": "Bangladesh phone provider"}),
    Setting("sms.provider", "Who sends SMS", "Calls and messages", "enum", "simulated",
            "Sends the receipt after each cash-out and a note after a missed call.",
            env="SATHI_SMS_PROVIDER", options=("simulated", "alpha"),
            option_labels={"simulated": "Demo inbox (no real SMS)",
                           "alpha": "Alpha SMS (sms.net.bd)"}),
    Setting("risk.step_up_enforced", "Always call for risky requests", "Safety checks", "bool",
            False, "When on, medium and high risk cash-outs can only be confirmed by phone call, "
            "not in the app.", env="SATHI_STEP_UP_ENFORCED"),
    Setting("risk.band_low_max", "Low risk ends at", "Safety checks", "float", 0.30,
            "Scores below this count as low risk.", minimum=0.05, maximum=0.90),
    Setting("risk.band_medium_max", "Medium risk ends at", "Safety checks", "float", 0.60,
            "Scores above this count as high risk and a supervisor also reviews them.",
            minimum=0.10, maximum=0.99),
    Setting("ai.provider_order", "Which AI writes case summaries", "AI helper", "enum",
            "gemini_first", "If the first AI is not available, the next one is used. "
            "\"Standard summary only\" never uses an online AI.",
            options=("gemini_first", "openai_first", "template_only"),
            option_labels={"gemini_first": "Gemini first, then GPT-4o",
                           "openai_first": "GPT-4o first, then Gemini",
                           "template_only": "Standard summary only (no online AI)"}),
    Setting("ai.gemini_model", "Gemini version", "AI helper", "text", "gemini-2.5-flash",
            "Leave as is unless Google tells you otherwise.", env="SATHI_GEMINI_MODEL",
            pattern=r"^[a-z0-9][a-z0-9.\-]{2,48}$"),
    Setting("ai.openai_model", "OpenAI version", "AI helper", "text", "gpt-4o",
            "Leave as is unless OpenAI tells you otherwise.", env="SATHI_OPENAI_MODEL",
            pattern=r"^[a-z0-9][a-z0-9.\-]{2,48}$"),
    Setting("ops.sla_urgent_minutes", "Secret help cases", "Time to respond", "int", 15,
            "How fast a supervisor should act when a customer asks for help secretly.",
            minimum=5, maximum=240, unit="min"),
    Setting("ops.sla_high_minutes", "Refused or risky requests", "Time to respond", "int", 60,
            "When the customer says they didn't ask, or the request looks risky.",
            minimum=15, maximum=1440, unit="min"),
    Setting("ops.sla_cash_gap_minutes", "Less cash received", "Time to respond", "int", 240,
            "When the customer got less cash than was paid.", minimum=30, maximum=2880,
            unit="min"),
    Setting("ops.sla_normal_minutes", "Other cases", "Time to respond", "int", 480,
            "Wrong amount typed, or too many wrong codes.", minimum=60, maximum=4320,
            unit="min"),
    Setting("calls.max_auto_attempts", "Automatic call attempts", "Call management", "int", 3,
            "How many times Sathi calls a customer who does not pick up before the check is "
            "marked unreachable (ignored).", minimum=1, maximum=10),
    Setting("calls.retry_delay_seconds", "Wait before calling again", "Call management", "int",
            120, "Delay before the first retry. Each later retry waits twice as long.",
            minimum=10, maximum=86400, unit="s"),
    Setting("calls.ring_timeout_seconds", "Ring time before 'no answer'", "Call management",
            "int", 45, "How long a demo call rings before it counts as missed. Real providers "
            "report missed calls themselves.", minimum=15, maximum=600, unit="s"),
    Setting("calls.unclear_confidence", "Speech confidence needed", "Call management", "float",
            0.6, "Spoken answers below this recognition confidence are not guessed: they are "
            "asked again, then sent to a supervisor.", minimum=0.1, maximum=0.99),
    Setting("sim.enabled", "Live traffic simulator", "Live traffic simulator", "bool", False,
            "Creates realistic cash-outs from synthetic customers and answers their calls "
            "(some confirm, some miss the call, some mumble, a few dispute). Everything runs "
            "through the real pipeline."),
    Setting("sim.rate_per_minute", "Cash-outs per minute", "Live traffic simulator", "int", 12,
            "How many simulated cash-outs to create each minute.", minimum=1, maximum=600),
    Setting("cost.usd_to_bdt", "1 US dollar in Taka", "Price estimates", "float", 122.0,
            "Only used to estimate costs.", minimum=50, maximum=300, unit="BDT"),
    Setting("cost.twilio_usd_per_min", "Twilio call price", "Price estimates", "float", 0.06,
            "Per minute, to Bangladesh mobiles.", minimum=0.005, maximum=1.0, unit="USD/min"),
    Setting("cost.bd_ivr_bdt_per_call", "Bangladesh provider call price", "Price estimates",
            "float", 0.85, "Per call. Update when you get a price quote.", minimum=0.1,
            maximum=20, unit="BDT/call"),
    Setting("cost.sms_bdt", "SMS price", "Price estimates", "float", 0.25, "Per message.",
            minimum=0.05, maximum=5, unit="BDT/SMS"),
    Setting("cost.avg_call_seconds", "Average call length", "Price estimates", "int", 45,
            "Used to work out the price of one call.", minimum=10, maximum=180, unit="s"),
)
BY_KEY = {s.key: s for s in REGISTRY}

SECRETS = (
    ("twilio", "Twilio account", ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")),
    ("bd_ivr", "Bangladesh IVR gateway",
     ("SATHI_BD_IVR_BASE_URL", "SATHI_BD_IVR_API_KEY", "SATHI_BD_IVR_WEBHOOK_SECRET")),
    ("public_url", "Public HTTPS API URL (webhooks)", ("SATHI_PUBLIC_API_URL",)),
    ("alpha_sms", "Alpha SMS API key", ("ALPHA_SMS_API_KEY",)),
    ("gemini", "Gemini API key", ("GEMINI_API_KEY",)),
    ("openai", "OpenAI API key", ("OPENAI_API_KEY",)),
)


def _coerce(setting: Setting, raw: Any) -> Any:
    kind = setting.kind
    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        raise SettingsError("Expected true or false.", setting.key)
    if kind == "enum":
        value = str(raw).strip().lower()
        if value not in setting.options:
            raise SettingsError(f"Must be one of: {', '.join(setting.options)}.", setting.key)
        return value
    if kind in ("int", "float"):
        if isinstance(raw, bool):
            raise SettingsError("Please type a number.", setting.key)
        try:
            value = int(raw) if kind == "int" else float(raw)
        except (TypeError, ValueError):
            raise SettingsError("Please type a number.", setting.key) from None
        if kind == "int" and float(raw) != value:
            raise SettingsError("Please type a whole number.", setting.key)
        if not (setting.minimum <= value <= setting.maximum):
            raise SettingsError(
                f"Please use a number between {setting.minimum:g} and {setting.maximum:g}.",
                setting.key)
        return value
    value = str(raw).strip()
    if setting.pattern and not re.fullmatch(setting.pattern, value):
        raise SettingsError("Invalid format.", setting.key)
    return value


class SettingsService:
    def __init__(self, get_connection: Callable, env: dict[str, str] | None = None) -> None:
        self._conn = get_connection
        self._env = env

    @property
    def env(self) -> dict[str, str]:
        """Server environment overlaid with credentials saved on the Settings page."""
        if self._env is not None:
            return self._env
        from app.settings.credentials import runtime_env

        return runtime_env(self._conn)

    def editable(self) -> bool:
        return self.env.get("SATHI_SETTINGS_EDITABLE", "true").strip().lower() == "true"

    def _overrides(self) -> dict[str, dict[str, Any]]:
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT key, value, updated_by, updated_at FROM app_settings;")
                rows = cur.fetchall()
        except Exception:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            raw = r[1]
            if isinstance(raw, str):
                # psycopg returns JSONB scalars as Python strings (e.g. "twilio").
                # The string is already the JSON value, so no second parse needed.
                value: Any = raw
            elif isinstance(raw, (dict, list, int, float, bool)) or raw is None:
                value = raw
            else:
                # Bytes or anything unexpected: try a defensive parse.
                try:
                    value = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
                except (ValueError, AttributeError):
                    value = raw
            out[r[0]] = {"value": value, "updated_by": r[2],
                         "updated_at": r[3].isoformat()}
        return out

    def _resolve(self, setting: Setting, overrides: dict[str, dict[str, Any]]
                 ) -> tuple[Any, str]:
        if setting.key in overrides:
            try:
                return _coerce(setting, overrides[setting.key]["value"]), "override"
            except SettingsError:
                pass
        if setting.env and self.env.get(setting.env, "").strip():
            try:
                return _coerce(setting, self.env[setting.env]), "env"
            except SettingsError:
                pass
        return setting.default, "default"

    def get(self, key: str) -> Any:
        return self._resolve(BY_KEY[key], self._overrides())[0]

    def values(self) -> dict[str, Any]:
        overrides = self._overrides()
        return {s.key: self._resolve(s, overrides)[0] for s in REGISTRY}

    # ------------------------------------------------------------------ secrets status
    def secret_status(self) -> list[dict[str, Any]]:
        env = self.env
        out = []
        for sid, label, names in SECRETS:
            present = [n for n in names if env.get(n, "").strip()]
            out.append({"id": sid, "label": label, "configured": len(present) == len(names),
                        "variables": [{"name": n, "set": n in present} for n in names]})
        return out

    def _configured(self, sid: str) -> bool:
        return next(s["configured"] for s in self.secret_status() if s["id"] == sid)

    def provider_ready(self, key: str, value: str) -> str | None:
        """Reason a provider cannot be selected yet, or None when it is ready."""
        public_ok = self.env.get("SATHI_PUBLIC_API_URL", "").startswith("https://")
        if key == "voice.provider" and value == "twilio":
            if not self._configured("twilio") or not public_ok:
                return "Save the Twilio account details and the public web address first."
        if key == "voice.provider" and value == "bd_http_ivr":
            if not self._configured("bd_ivr") or not public_ok:
                return ("Save the Bangladesh provider details and the public web address "
                        "first.")
        if key == "sms.provider" and value == "alpha" and not self._configured("alpha_sms"):
            return "Save the Alpha SMS API key first."
        return None

    # ------------------------------------------------------------------ view and update
    def describe(self) -> dict[str, Any]:
        overrides = self._overrides()
        items = []
        for s in REGISTRY:
            value, source = self._resolve(s, overrides)
            item = {
                "key": s.key, "label": s.label, "group": s.group, "type": s.kind,
                "value": value, "default": s.default, "source": source, "help": s.help,
                "env": s.env, "unit": s.unit,
            }
            if s.kind == "enum":
                item["options"] = [
                    {"value": o, "label": s.option_labels.get(o, o),
                     "unavailable_reason": self.provider_ready(s.key, o)}
                    for o in s.options
                ]
            if s.minimum is not None:
                item["min"], item["max"] = s.minimum, s.maximum
            if source == "override":
                item["updated_by"] = overrides[s.key]["updated_by"]
                item["updated_at"] = overrides[s.key]["updated_at"]
            items.append(item)
        book = load_phone_book(self.env)
        return {
            "editable": self.editable(),
            "groups": list(dict.fromkeys(s.group for s in REGISTRY)),
            "items": items,
            "secrets": self.secret_status(),
            "phone_book": [{"user_id": u, "phone": mask_number(n)}
                           for u, n in sorted(book.items())],
            "unit_costs": self.unit_costs(),
        }

    def unit_costs(self) -> dict[str, float]:
        v = self.values()
        minutes = v["cost.avg_call_seconds"] / 60
        return {
            "twilio_bdt_per_call": round(v["cost.twilio_usd_per_min"] * minutes
                                         * v["cost.usd_to_bdt"], 2),
            "bd_ivr_bdt_per_call": round(v["cost.bd_ivr_bdt_per_call"], 2),
            "sms_bdt": round(v["cost.sms_bdt"], 2),
        }

    # ------------------------------------------------------------------ readiness
    # Env vars each provider needs before it can be selected. Public so the
    # Settings page can render "what to put in .env" hints.
    REQUIRED_ENV: dict[str, tuple[str, ...]] = {
        "twilio": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"),
        "bd_http_ivr": ("SATHI_BD_IVR_BASE_URL", "SATHI_BD_IVR_API_KEY",
                        "SATHI_BD_IVR_WEBHOOK_SECRET"),
        "alpha_sms": ("ALPHA_SMS_API_KEY",),
        "gemini": ("GEMINI_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
    }
    # One-line copy shown on the panel so the operator knows exactly what
    # to set in .env before flipping the corresponding selector.
    HINTS: dict[str, str] = {
        "twilio": "Save the Twilio account details and the public web address under "
                  "Service accounts, then choose Twilio under Calls and messages.",
        "bd_http_ivr": "Save the provider's web address, API key and secret, plus the public "
                       "web address, under Service accounts. We are still waiting for a "
                       "Bangladesh provider to sign up.",
        "alpha_sms": "Save the Alpha SMS API key under Service accounts, then choose Alpha "
                     "SMS under Calls and messages.",
        "gemini": "Save the Gemini API key under Service accounts. Gemini writes case "
                  "summaries first.",
        "openai": "Save the OpenAI API key under Service accounts. It is used when Gemini is "
                  "not available.",
    }

    def readiness(self) -> dict[str, Any]:
        """Return what the operator needs to make the currently selected
        providers work.

        The function is intentionally cheap \u2014 it inspects the runtime
        Settings overrides + env + env, but does not make any network call.
        The Settings page renders this directly; the live-probe button
        calls `readiness(include_probes=True)` to add per-provider probe
        results.
        """
        values = self.values()
        env = self.env
        voice = values["voice.provider"]
        sms = values["sms.provider"]
        ai_order = values["ai.provider_order"]
        public_url_ok = env.get("SATHI_PUBLIC_API_URL", "").startswith("https://")

        def env_status(provider_id: str) -> list[dict[str, Any]]:
            return [{"name": n, "set": bool(env.get(n, "").strip())}
                    for n in self.REQUIRED_ENV[provider_id]]

        def requires_public_url(provider_id: str) -> bool:
            return provider_id in ("twilio", "bd_http_ivr")

        def panel(provider_id: str) -> dict[str, Any]:
            env_vars = env_status(provider_id)
            if requires_public_url(provider_id):
                env_vars.append({
                    "name": "SATHI_PUBLIC_API_URL",
                    "set": public_url_ok,
                })
            return {
                "provider_id": provider_id,
                "env_vars": env_vars,
                "hint": self.HINTS.get(provider_id, ""),
                "vendor_confirmed": provider_id != "bd_http_ivr",
            }

        twilio_p = panel("twilio")
        bd_p = panel("bd_http_ivr")
        alpha_p = panel("alpha_sms")
        gemini_p = panel("gemini")
        openai_p = panel("openai")

        # Selection: which provider is "the one that will be called right now"?
        # - voice: only the selected value is "the one"
        # - sms: only the selected value
        # - ai: gemini is the primary under "gemini_first"; openai is always
        #      part of the chain unless ai.template_only
        panels = []
        for p in (twilio_p, bd_p):
            p["selected"] = voice == p["provider_id"]
            p["ready"] = p["selected"] and all(v["set"] for v in p["env_vars"])
            panels.append(p)
        alpha_p["selected"] = sms == "alpha"
        alpha_p["ready"] = alpha_p["selected"] and all(
            v["set"] for v in alpha_p["env_vars"])
        panels.append(alpha_p)

        gemini_p["selected"] = ai_order == "gemini_first"
        gemini_p["ready"] = gemini_p["selected"] and all(
            v["set"] for v in gemini_p["env_vars"])
        panels.append(gemini_p)
        openai_p["selected"] = ai_order in ("gemini_first", "openai_first")
        openai_p["ready"] = openai_p["selected"] and all(
            v["set"] for v in openai_p["env_vars"])
        panels.append(openai_p)

        return {
            "selected": {
                "voice_provider": voice,
                "sms_provider": sms,
                "ai_provider_order": ai_order,
                "public_url_ok": public_url_ok,
            },
            "panels": panels,
            "all_ready": all(p["ready"] or not p["selected"] for p in panels),
        }

    def update(self, changes: dict[str, Any], actor: str) -> dict[str, Any]:
        if not self.editable():
            raise SettingsError("Settings are read-only on this deployment.")
        if not changes:
            raise SettingsError("No changes submitted.")
        current = self.values()
        clean: dict[str, Any] = {}
        for key, raw in changes.items():
            if key not in BY_KEY:
                raise SettingsError("Unknown setting.", key)
            clean[key] = _coerce(BY_KEY[key], raw)
            if BY_KEY[key].kind == "enum":
                reason = self.provider_ready(key, clean[key])
                if reason:
                    raise SettingsError(reason, key)
        merged = {**current, **clean}
        if merged["risk.band_low_max"] >= merged["risk.band_medium_max"]:
            raise SettingsError(
                "\"Low risk ends at\" must be smaller than \"Medium risk ends at\".",
                "risk.band_low_max")
        with self._conn() as conn:
            with conn.cursor() as cur:
                for key, value in clean.items():
                    cur.execute(
                        """
                        INSERT INTO app_settings (key, value, updated_by) VALUES (%s, %s::jsonb, %s)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                            updated_by = EXCLUDED.updated_by, updated_at = now();
                        """,
                        (key, json.dumps(value), actor),
                    )
                cur.execute(
                    "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES (%s, 'settings_updated', 'settings', 'runtime', 'v1.0', "
                    "%s::jsonb, now());",
                    (actor, json.dumps({k: {"old": current[k], "new": v}
                                        for k, v in clean.items()})),
                )
            conn.commit()
        return self.describe()

    def reset(self, key: str, actor: str) -> dict[str, Any]:
        if not self.editable():
            raise SettingsError("Settings are read-only on this deployment.")
        if key not in BY_KEY:
            raise SettingsError("Unknown setting.", key)
        old = self.get(key)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM app_settings WHERE key = %s;", (key,))
                cur.execute(
                    "INSERT INTO audit_log (actor, action, entity, entity_id, policy_version, "
                    "detail, ts) VALUES (%s, 'settings_reset', 'settings', %s, 'v1.0', "
                    "%s::jsonb, now());",
                    (actor, key, json.dumps({"old": old})),
                )
            conn.commit()
        return self.describe()
