"""Provider readiness probes shared by the Settings page and `scripts/preflight.py`.

Every probe here is read-only and free:

- Twilio: GET the account resource (no call is created).
- Alpha SMS: GET the balance API (no SMS is sent).
- Gemini / OpenAI: GET the model resource (no tokens are generated).
- Bangladesh IVR: GET the gateway base URL with the Bearer key (no call is created).

Earlier drafts of this module created real calls, sent a real SMS to a real-format
Bangladeshi number and ran paid generations, while documenting the opposite. The paid
checks now live only behind explicit, admin-gated, rate-limited "test call" and
"test SMS" actions on the Settings page.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from app.settings import probes

DEFAULT_TIMEOUT = 8.0


@dataclass
class ProbeResult:
    name: str
    env_ok: bool
    probe_ok: bool | None  # None = skipped because credentials are missing
    detail: str
    ready: bool

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "env_ok": self.env_ok, "probe_ok": self.probe_ok,
                "detail": self.detail, "ready": self.ready}


def _wrap(name: str, raw: dict) -> ProbeResult:
    missing = raw.get("http_status") is None and str(raw.get("detail", "")).startswith(
        "Missing")
    if missing:
        return ProbeResult(name, False, None, raw["detail"], False)
    return ProbeResult(name, True, bool(raw["ok"]), raw["detail"], bool(raw["ok"]))


def _models(env: dict[str, str]) -> tuple[str, str]:
    return (env.get("SATHI_GEMINI_MODEL", "gemini-2.5-flash"),
            env.get("SATHI_OPENAI_MODEL", "gpt-4o"))


PROBES: dict[str, Callable[[dict[str, str], float], ProbeResult]] = {
    "twilio": lambda env, _t: _wrap("twilio", probes.probe_twilio(env)),
    "alpha_sms": lambda env, _t: _wrap("alpha_sms", probes.probe_alpha(env)),
    "gemini": lambda env, _t: _wrap("gemini", probes.probe_gemini(env, _models(env)[0])),
    "openai": lambda env, _t: _wrap("openai", probes.probe_openai(env, _models(env)[1])),
    "bd_http_ivr": lambda env, _t: _wrap("bd_http_ivr", probes.probe_bd_ivr(env)),
}


def run_all(env: dict[str, str] | None = None,
            timeout: float = DEFAULT_TIMEOUT) -> list[ProbeResult]:
    """Run every probe in fixed order."""
    merged = env if env is not None else dict(os.environ)
    return [PROBES[name](merged, timeout) for name in PROBES]


def run_one(name: str, env: dict[str, str] | None = None,
            timeout: float = DEFAULT_TIMEOUT) -> ProbeResult:
    """Run one named probe. Raises KeyError if the name is unknown."""
    if name not in PROBES:
        raise KeyError(f"unknown probe {name!r}; available: {sorted(PROBES)}")
    merged = env if env is not None else dict(os.environ)
    return PROBES[name](merged, timeout)
