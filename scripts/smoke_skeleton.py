#!/usr/bin/env python3
"""Smoke checker for Phase 0 Docker Compose skeleton.

Verifies API health endpoint and frontend static page using Python stdlib.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Callable


def check_api(url: str, timeout: float = 5.0) -> bool:
    """Check API health endpoint returning HTTP 200 and status ok."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                print(f"[API] Unexpected status code: {response.status}")
                return False
            payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "ok":
                print(f"[API] Health check passed ({url} -> 200 OK: {payload})")
                return True
            print(f"[API] Unexpected payload: {payload}")
            return False
    except Exception as exc:
        print(f"[API] Connection attempt failed ({url}): {exc}")
        return False


def check_frontend(url: str, timeout: float = 5.0) -> bool:
    """Check frontend page returning HTTP 200, Sathi Console title, and root element."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                print(f"[Frontend] Unexpected status code: {response.status}")
                return False
            body = response.read().decode("utf-8", errors="replace")
            has_title = "<title>Sathi Console</title>" in body or bool(
                re.search(r"<title[^>]*>\s*Sathi Console\s*</title>", body, re.IGNORECASE)
            )
            has_root = 'id="root"' in body or "id='root'" in body
            if has_title and has_root:
                print(f"[Frontend] Sathi Console page check passed ({url} -> 200 OK)")
                return True
            print(f"[Frontend] Unexpected page content from {url}")
            return False
    except Exception as exc:
        print(f"[Frontend] Connection attempt failed ({url}): {exc}")
        return False


def wait_for_service(
    name: str, check_fn: Callable[[str, float], bool], url: str, max_retries: int, delay: float
) -> bool:
    """Retry check_fn until it succeeds or max_retries is reached."""
    print(f"Checking {name} at {url} (max {max_retries} retries)...")
    for attempt in range(1, max_retries + 1):
        if check_fn(url, 5.0):
            return True
        if attempt < max_retries:
            time.sleep(delay)
    return False


def main() -> int:
    """Parse arguments and execute smoke checks against API and frontend."""
    parser = argparse.ArgumentParser(
        description="Smoke test for running compose stack"
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("API_URL", "http://127.0.0.1:18000/health"),
        help="API health check URL (default: http://127.0.0.1:18000/health)",
    )
    parser.add_argument(
        "--frontend-url",
        default=os.getenv("FRONTEND_URL", "http://127.0.0.1:13000/"),
        help="Frontend URL (default: http://127.0.0.1:13000/)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("SMOKE_RETRIES", "30")),
        help="Maximum retry attempts per service (default: 30)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=float(os.getenv("SMOKE_DELAY", "1.0")),
        help="Delay in seconds between retries (default: 1.0)",
    )

    args = parser.parse_args()

    api_ok = wait_for_service(
        "API", check_api, args.api_url, args.retries, args.delay
    )
    if not api_ok:
        print(f"FAIL: API failed smoke check at {args.api_url}", file=sys.stderr)
        return 1

    frontend_ok = wait_for_service(
        "Frontend", check_frontend, args.frontend_url, args.retries, args.delay
    )
    if not frontend_ok:
        print(
            f"FAIL: Frontend failed smoke check at {args.frontend_url}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Skeleton smoke checks succeeded for both API and frontend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
