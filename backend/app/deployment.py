"""Deployment mode: what a given environment may do.

SATHI_DEPLOYMENT_MODE:
- ``local`` (default): controlled developer setup. Settings may be edited when
  SATHI_SETTINGS_EDITABLE=true; every provider the operator configures may be used.
- ``public_demo``: a public, synthetic-data deployment whose staff PINs are published.
  Management is read-only (settings, credentials, staff and test accounts), real call and
  SMS providers and online AI models are never used, and provider probes are refused. The
  synthetic demo sign-in keeps working so judges can try the workflow.
- ``pilot``: a governed deployment with real partners. Behaves like ``local`` here; it exists so
  documents and the UI can name it. Pilot hardening (separate credentials, SSO, restricted
  database grants) is NOT implemented by this switch.

An unknown value is treated as ``public_demo`` (fail closed).
"""

from __future__ import annotations

import os

MODES = ("local", "public_demo", "pilot")

# Settings that a public demo pins so a saved override or an environment variable cannot
# switch on a paid or external service.
PUBLIC_DEMO_PINNED = {
    "voice.provider": "simulated",
    "sms.provider": "simulated",
    "ai.provider_order": "template_only",
}

PUBLIC_DEMO_MESSAGE = ("This is a public simulated demo. Management actions and real providers "
                       "are disabled here.")


def deployment_mode(env: dict[str, str] | None = None) -> str:
    raw = (env if env is not None else os.environ).get("SATHI_DEPLOYMENT_MODE", "local")
    value = raw.strip().lower() or "local"
    return value if value in MODES else "public_demo"


def is_public_demo(env: dict[str, str] | None = None) -> bool:
    return deployment_mode(env) == "public_demo"


def blocked_response():
    """403 envelope for a management action refused in the public demo."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=403, content={"error": {
        "code": "PUBLIC_DEMO_READ_ONLY", "message": PUBLIC_DEMO_MESSAGE}})


def describe() -> dict:
    mode = deployment_mode()
    public = mode == "public_demo"
    return {
        "mode": mode,
        "simulated_only": public,
        "management_read_only": public,
        "real_providers_allowed": not public,
        "online_ai_allowed": not public,
        "label": ("Public simulated demo: synthetic data, read-only management" if public
                  else "Local or pilot deployment"),
    }
