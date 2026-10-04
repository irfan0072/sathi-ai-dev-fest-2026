"""Send-money advisory written from community alerts.

When a receiver's number appears in community scam-alert posts, the payer sees a calm
warning before sending. An LLM may word it, but it never calls the receiver a scammer: the
reports are unproven claims by other customers. Only structured facts (counts, categories,
dates) go to the model, never report text, so a report cannot inject instructions. Every
LLM answer is checked; anything accusatory, too long or malformed falls back to a fixed
template, which is also used when no API key is set.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

CATEGORY_TEXT = {
    "not_delivered": ("paid but the product did not arrive", "টাকা দিয়েছেন কিন্তু পণ্য পাননি"),
    "fake_product": ("received a different product than promised",
                     "যা বলা হয়েছিল তার চেয়ে ভিন্ন পণ্য পেয়েছেন"),
    "advance_fee": ("paid in advance and then lost contact",
                    "আগাম টাকা দেওয়ার পর আর যোগাযোগ করতে পারেননি"),
    "impersonation": ("were told the caller was from upay, a bank or a known shop",
                      "ফোনকারী নিজেকে ইউপে, ব্যাংক বা পরিচিত দোকানের লোক বলেছিলেন"),
    "investment": ("were promised money back with high profit",
                   "অনেক লাভসহ টাকা ফেরতের প্রতিশ্রুতি পেয়েছিলেন"),
    "job_offer": ("were asked to pay a fee for a job or training",
                  "চাকরি বা প্রশিক্ষণের জন্য ফি দিতে বলা হয়েছিল"),
    "other": ("had a problem after paying", "টাকা দেওয়ার পর সমস্যায় পড়েছেন"),
}

# The warning suggests caution; it must never accuse. Checked on every LLM answer.
ACCUSATORY = re.compile(
    r"scam|fraud|cheat|thief|criminal|steal|stole|con\s?man|liar|fake\s+seller|"
    r"প্রতারক|প্রতারণা|প্রতারিত|চোর|ঠগ|জালিয়াত|ভুয়া বিক্রেতা|অপরাধী",
    re.IGNORECASE)
DIGITS = re.compile(r"\d{6,}")

SYSTEM = """You write a short, calm warning shown in a mobile wallet app before a customer
sends money to a personal number. Other customers posted community alerts about this number.
These alerts are unproven claims, so you must NOT say the receiver is a scammer, fraud,
cheat or criminal, and must not use those words (or Bangla প্রতারক/প্রতারণা/চোর) at all.
Say what other customers reported, that it is not confirmed, and give simple checks before
paying. Never include phone numbers or amounts. Plain words a first-time phone user can follow.
Reply with JSON only:
{"title": "<max 8 words, English>", "message": "<max 2 sentences, English>",
 "message_bn": "<same meaning in simple Bangla>",
 "tips": ["<max 3 short English tips>"], "tips_bn": ["<the same tips in Bangla>"]}"""

_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
CACHE_SECONDS = 600
LLM_TIMEOUT_SECONDS = 6.0


def _facts(check: dict[str, Any]) -> dict[str, Any]:
    cats = [c for c in (check.get("report_categories") or []) if c in CATEGORY_TEXT]
    return {"community_alerts": int(check.get("community_reports") or 0),
            "checked_by_upay": int(check.get("verified_reports") or 0),
            "what_people_reported": [CATEGORY_TEXT[c][0] for c in cats] or
            [CATEGORY_TEXT["other"][0]],
            "warning_level": check.get("warning_level", "caution")}


BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def template(check: dict[str, Any]) -> dict[str, Any]:
    n = int(check.get("community_reports") or 0)
    verified = int(check.get("verified_reports") or 0)
    cats = [c for c in (check.get("report_categories") or []) if c in CATEGORY_TEXT] or ["other"]
    en = "; ".join(CATEGORY_TEXT[c][0] for c in cats[:2])
    bn = "; ".join(CATEGORY_TEXT[c][1] for c in cats[:2])
    checked = (f" upay looked at {verified} of them." if verified else
               " These alerts are not confirmed.")
    n_bn, verified_bn = str(n).translate(BN_DIGITS), str(verified).translate(BN_DIGITS)
    checked_bn = (f" এর মধ্যে {verified_bn}টি ইউপে যাচাই করেছে।" if verified else
                  " এই সতর্কবার্তাগুলো এখনো নিশ্চিত নয়।")
    return {
        "title": "Check before you send",
        "message": f"This number appears in {n} community alert(s). Other customers said they "
                   f"{en}.{checked}",
        "message_bn": f"এই নম্বরটি কমিউনিটির {n_bn}টি সতর্কবার্তায় আছে। অন্য গ্রাহকরা বলেছেন তাঁরা "
                      f"{bn}।{checked_bn}",
        "tips": ["Send only if you know this person.",
                 "For online shopping, ask for cash on delivery.",
                 "Never send an advance to unlock a prize, job or loan."],
        "tips_bn": ["এই মানুষটিকে চিনলেই টাকা পাঠান।",
                    "অনলাইনে কেনাকাটায় ক্যাশ অন ডেলিভারি চান।",
                    "পুরস্কার, চাকরি বা ঋণের জন্য আগাম টাকা পাঠাবেন না।"],
        "source": "template",
    }


def _valid(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key, limit in (("title", 80), ("message", 320), ("message_bn", 480)):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            return None
        out[key] = value.strip()
    for key in ("tips", "tips_bn"):
        tips = raw.get(key)
        if not isinstance(tips, list) or not 1 <= len(tips) <= 3 or not all(
                isinstance(t, str) and 0 < len(t) <= 160 for t in tips):
            return None
        out[key] = [t.strip() for t in tips]
    text = " ".join([out["title"], out["message"], out["message_bn"], *out["tips"],
                     *out["tips_bn"]])
    if ACCUSATORY.search(text) or DIGITS.search(text):
        return None
    return out


def advise(check: dict[str, Any], clients: list[Any] | None = None) -> dict[str, Any] | None:
    """Advisory for a recipient check, or None when the number has no community alerts."""
    if not check.get("community_reports"):
        return None
    facts = _facts(check)
    key = (check.get("number"), facts["community_alerts"], facts["checked_by_upay"],
           tuple(facts["what_people_reported"]))
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    result = None
    for client in clients or []:
        try:
            if hasattr(client, "timeout"):
                client.timeout = min(client.timeout, LLM_TIMEOUT_SECONDS)
            result = _valid(json.loads(client.complete(SYSTEM, json.dumps(facts))))
        except Exception:
            result = None
        if result:
            result["source"] = getattr(client, "name", "llm")
            break
    result = result or template(check)
    with _lock:
        _cache[key] = (time.monotonic(), result)
    return result
