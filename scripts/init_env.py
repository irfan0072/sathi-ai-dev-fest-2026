#!/usr/bin/env python3
"""Local initialization helper to generate ignored .env signing secret fail-closed.

- Creates .env from .env.example if missing.
- Replaces missing or placeholder JWT_SECRET with a cryptographically secure secret.
- Never prints or commits server signing secrets.
- Preserves existing valid configuration without overwriting.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

PLACEHOLDER_SECRETS = {
    "",
    "CHANGE_ME",
    "YOUR_SECRET_HERE",
    "YOUR_KEY_HERE",
    "CHANGEME",
}


def init_env(env_path: Path | None = None, example_path: Path | None = None) -> bool:
    """Initialize or update .env file safely."""
    repo_root = Path(__file__).resolve().parent.parent
    target_env = env_path or (repo_root / ".env")
    example_env = example_path or (repo_root / ".env.example")

    if not target_env.exists():
        if example_env.exists():
            template = example_env.read_text(encoding="utf-8")
        else:
            template = (
                "DATABASE_URL=postgresql://sathi:CHANGE_ME@localhost:5432/sathi\n"
                "JWT_SECRET=CHANGE_ME\n"
                "SATHI_CONFIG=data/config.yaml\n"
            )

        new_secret = secrets.token_hex(32)
        if "JWT_SECRET=CHANGE_ME" in template:
            content = template.replace("JWT_SECRET=CHANGE_ME", f"JWT_SECRET={new_secret}")
        elif "JWT_SECRET=" in template:
            content = re.sub(r"JWT_SECRET=.*", f"JWT_SECRET={new_secret}", template)
        else:
            content = template.rstrip() + f"\nJWT_SECRET={new_secret}\n"

        target_env.write_text(content, encoding="utf-8")
        print("Initialized .env configuration with fresh random signing secret.")
        return True

    # .env exists: check JWT_SECRET
    content = target_env.read_text(encoding="utf-8")
    secret_match = re.search(r"^JWT_SECRET=(.*)$", content, re.MULTILINE)

    needs_update = False
    if not secret_match:
        needs_update = True
    else:
        current_val = secret_match.group(1).strip()
        if current_val in PLACEHOLDER_SECRETS:
            needs_update = True

    if needs_update:
        new_secret = secrets.token_hex(32)
        if secret_match:
            new_content = re.sub(
                r"^JWT_SECRET=.*$",
                f"JWT_SECRET={new_secret}",
                content,
                flags=re.MULTILINE,
            )
        else:
            new_content = content.rstrip() + f"\nJWT_SECRET={new_secret}\n"

        target_env.write_text(new_content, encoding="utf-8")
        print("Updated .env with fresh random signing secret.")
        return True
    else:
        print(
            "Existing .env configuration has valid signing secret; "
            "preserved without modification."
        )
        return False


def main() -> int:
    init_env()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
