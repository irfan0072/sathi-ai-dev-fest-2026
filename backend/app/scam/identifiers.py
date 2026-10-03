"""Normalise the ways people name a seller: upay numbers, social handles, links."""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
MSISDN_RE = re.compile(r"^01[3-9]\d{8}$")
TYPES = ("upay_number", "facebook", "instagram", "whatsapp", "telegram", "website", "other")


class IdentifierError(ValueError):
    pass


def normalize_msisdn(raw: str) -> str:
    digits = re.sub(r"\D", "", (raw or "").translate(BANGLA_DIGITS))
    if digits.startswith("880"):
        digits = digits[2:]
    if not MSISDN_RE.fullmatch(digits):
        raise IdentifierError("Enter an 11-digit Bangladeshi mobile number, like 01712345678.")
    return digits


def mask_msisdn(msisdn: str) -> str:
    return f"{msisdn[:3]}•••••{msisdn[-3:]}" if msisdn and len(msisdn) == 11 else "•••"


def normalize(identifier_type: str, raw: str) -> tuple[str, str]:
    """Return (normalised key, display text). Keys are what searches match on."""
    if identifier_type not in TYPES:
        raise IdentifierError("Unknown identifier type.")
    value = (raw or "").strip()
    if identifier_type in ("upay_number", "whatsapp"):
        number = normalize_msisdn(value)
        return f"{identifier_type}:{number}", number
    if not 3 <= len(value) <= 200:
        raise IdentifierError("Enter the page, handle or link (3-200 characters).")
    if identifier_type == "website":
        url = value if "://" in value else f"https://{value}"
        host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
        if "." not in host:
            raise IdentifierError("Enter a website address, like shop-example.com.")
        return f"website:{host}", host
    if identifier_type in ("facebook", "instagram", "telegram"):
        handle = value
        if "/" in value:
            path = urllib.parse.urlsplit(value if "://" in value else f"https://{value}").path
            parts = [p for p in path.split("/") if p and p not in ("pg", "people", "profile.php")]
            handle = parts[0] if parts else value
        handle = handle.lstrip("@").lower()
        handle = re.sub(r"[^a-z0-9._-]", "", handle)
        if len(handle) < 3:
            raise IdentifierError("Enter the page name or link.")
        return f"{identifier_type}:{handle}", f"@{handle}"
    text = re.sub(r"\s+", " ", value.lower())[:120]
    return f"other:{text}", value[:120]


def guess_type(raw: str) -> str:
    value = (raw or "").strip().lower().translate(BANGLA_DIGITS)
    if re.fullmatch(r"[+\d\s-]{11,16}", value):
        return "upay_number"
    for kind in ("facebook", "instagram", "telegram"):
        if kind in value or (kind == "facebook" and "fb.com" in value):
            return kind
    if "wa.me" in value or "whatsapp" in value:
        return "whatsapp"
    if re.search(r"\.[a-z]{2,}(/|$)", value):
        return "website"
    return "other"


def reporter_hash(user_id: str) -> str:
    """Keyed hash: stable per customer, but nobody can turn it back into the customer."""
    pepper = os.environ.get("JWT_SECRET", "sathi-community-pepper")
    return hashlib.sha256(f"community:{pepper}:{user_id}".encode()).hexdigest()
