#!/usr/bin/env python3
"""Bangladesh JSON IVR stand-in for local live integration tests.

This is a tiny, deliberately simple gateway stub used ONLY to exercise the
Sathi API's Bangladesh IVR contract end-to-end without depending on a real
vendor (per docs/live-mode.md, "no Bangladesh vendor has confirmed the JSON
contract yet — vendor mapping is pending").

It speaks exactly the contract documented in docs/live-mode.md:

  POST {this} /calls
    Body: {"to", "callback_url", "status_url", "language", "prompt": {...},
           "gather": {...}, "client_ref"}
    Reply: {"call_id": "..."}

Then the stand-in asynchronously POSTs a signed event back to the API:

  POST {callback_url}
    Headers: X-Sathi-Signature: hex(HMAC-SHA256(secret, raw_body))
    Body: {"event": "answered"} then {"event": "digits", "digits": "3000"}

The stand-in is enabled ONLY when SATHI_LIVE_TESTS=1. Default behaviour
(SATHI_VOICE_PROVIDER=simulated) is unchanged.

Usage:
  scripts/bd_ivr_standin.py [--port 18443] [--scenario digits] [--delay 0.5]

Environment variables:
  SATHI_BD_IVR_API_KEY        Bearer key the stand-in expects from the API.
  SATHI_BD_IVR_WEBHOOK_SECRET Shared HMAC secret used to sign callback bodies.
  SATHI_BD_IVR_CALL_DELAY     Seconds between /calls and the first callback.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timezone

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

LOG = logging.getLogger("bd_ivr_standin")

# Default test key/secret; overridable through env. The defaults are
# deliberately long enough to satisfy the 16-char minimum in
# app/voice/providers.py:BdHttpIvrProvider.__init__.
DEFAULT_API_KEY = "demo-bd-ivr-api-key-for-live-integration-only-please-rotate"
DEFAULT_WEBHOOK_SECRET = "demo-bd-ivr-webhook-secret-please-rotate-16-chars-min"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


app = FastAPI(title="Sathi BD-IVR stand-in", version="1.0.0")


def _expected_api_key() -> str:
    return os.environ.get("SATHI_BD_IVR_API_KEY", DEFAULT_API_KEY)


def _signing_secret() -> str:
    secret = os.environ.get("SATHI_BD_IVR_WEBHOOK_SECRET", DEFAULT_WEBHOOK_SECRET)
    if len(secret) < 16:
        raise RuntimeError(
            "SATHI_BD_IVR_WEBHOOK_SECRET must be at least 16 characters"
        )
    return secret


def _sign_body(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "bd_ivr_standin", "ts": _now()}


@app.post("/calls")
async def place_call(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Receive a /calls request and schedule the signed callback."""
    expected = f"Bearer {_expected_api_key()}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid Bearer key")
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc

    callback_url = body.get("callback_url")
    status_url = body.get("status_url") or callback_url
    if not callback_url:
        raise HTTPException(status_code=400, detail="callback_url is required")

    call_id = f"BDI{secrets.token_hex(8)}"
    LOG.info(
        "standin /calls call_id=%s to=%s callback=%s language=%s",
        call_id,
        body.get("to"),
        callback_url,
        body.get("language"),
    )

    scenario = os.environ.get("SATHI_BD_IVR_STANDIN_SCENARIO", "digits").lower()
    delay = float(os.environ.get("SATHI_BD_IVR_CALL_DELAY", "0.5"))
    asyncio.create_task(
        _post_callbacks(
            call_id=call_id,
            callback_url=str(callback_url),
            status_url=str(status_url),
            scenario=scenario,
            delay=delay,
        )
    )

    return {"call_id": call_id, "status": "queued"}


async def _post_callbacks(
    call_id: str,
    callback_url: str,
    status_url: str,
    scenario: str,
    delay: float,
) -> None:
    """Replay a scripted event sequence back to the API, signed."""
    secret = _signing_secret()
    await asyncio.sleep(delay)

    async with httpx.AsyncClient(timeout=10.0) as client:
        for event in _scenario_events(scenario):
            target = callback_url if event["event"] in {"answered", "digits"} else status_url
            body = json.dumps(event, ensure_ascii=False).encode()
            signature = _sign_body(secret, body)
            headers = {
                "Content-Type": "application/json",
                "X-Sathi-Signature": signature,
                "X-Standin-Call-Id": call_id,
            }
            try:
                resp = await client.post(target, content=body, headers=headers)
            except httpx.HTTPError as exc:
                LOG.warning("standin callback error to %s: %s", target, exc)
                return
            LOG.info(
                "standin -> %s %s %s body=%s",
                target,
                resp.status_code,
                event["event"],
                event.get("digits") or event.get("status") or "",
            )


def _scenario_events(name: str) -> list[dict[str, object]]:
    """Built-in scripted sequences. Tests can pick the scenario via env."""
    if name == "answered_only":
        return [{"event": "answered"}, {"event": "status", "status": "completed"}]
    if name == "missed":
        return [{"event": "status", "status": "no-answer"}]
    # Default: answered + digits 3000 + completed (mimics a real cash-out).
    return [
        {"event": "answered"},
        {"event": "digits", "digits": "3000"},
        {"event": "status", "status": "completed"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bangladesh IVR stand-in for live tests")
    parser.add_argument("--port", type=int, default=18443)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--scenario",
        default="digits",
        choices=("digits", "answered_only", "missed"),
        help="Pre-scripted callback sequence to replay after /calls",
    )
    args = parser.parse_args()
    os.environ.setdefault("SATHI_BD_IVR_STANDIN_SCENARIO", args.scenario)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOG.info(
        "bd_ivr_standin listening on http://%s:%s scenario=%s",
        args.host,
        args.port,
        args.scenario,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())