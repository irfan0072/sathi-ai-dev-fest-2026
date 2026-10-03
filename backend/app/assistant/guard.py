"""Guardrails for the customer assistant.

Threats handled:
- Prompt injection ("ignore your instructions", "you are now ...", system-prompt probing),
  in English, Bangla and Banglish.
- Secret fishing: PIN, OTP, password, card numbers. Sathi never needs them and says so.
- Other people's data: other customer or agent IDs, phone numbers, "my brother's account".
- Probing internal fraud signals ("was my agent flagged?", risk scores, case status). The
  customer only ever sees neutral states, so a person forcing them cannot learn anything.

Output side: every reply is redacted (foreign IDs, phone numbers, emails, long digit runs)
and every number in an AI-written reply must come from the customer's own facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
MAX_MESSAGE = 500

INJECTION = [
    r"ignore (all |any |the )?(previous|prior|above|earlier|your)? ?(instruction|rule|prompt)",
    r"disregard (all |the |your )?(previous|prior|above|instruction|rule)",
    r"forget (all |your |the )?(instruction|rule|prompt|previous)",
    r"system prompt", r"developer mode", r"jail ?break", r"\bdan\b", r"you are now",
    r"act as (an? )?(admin|developer|supervisor|system|root|god)", r"pretend (to be|you)",
    r"reveal (your|the) (prompt|instruction|rule|system)", r"print (your|the) (prompt|rules)",
    r"override", r"sudo", r"admin (mode|access|password)", r"<\s*/?\s*(system|assistant)",
    r"\[\s*(system|inst)\s*\]", r"repeat (the )?(text|words) above",
    r"নির্দেশ(না)? (উপেক্ষা|ভুলে|বাদ)", r"আগের (সব )?নির্দেশ", r"সিস্টেম প্রম্পট",
    r"instruction (ignore|bhule|vule|bad)", r"rules? (bhule|vule) (jao|jan|jaw)",
    r"tumi ekhon (admin|developer)", r"তুমি এখন",
]
SECRETS = [r"\bpin\b", r"\botp\b", r"pass ?word", r"\bcvv\b", r"card number",
           r"পিন", r"ওটিপি", r"পাসওয়ার্ড", r"গোপন নম্বর", r"pin ?code", r"pin number"]
OTHER_PEOPLE = [
    r"\b(someone|somebody|another|other) (else'?s?|person'?s?|customer'?s?|user'?s?)",
    r"\b(my|his|her|their) (wife|husband|brother|sister|father|mother|friend|son|daughter)'?s? "
    r"(account|balance|number|transaction)",
    r"\b(agent'?s?) (phone|number|address|balance|details)",
    r"অন্য (কারো|কারও|গ্রাহক|কাস্টমার)", r"(?:^|\s)(ভাই|বোন|স্ত্রী|স্বামী|বাবা|মা|বন্ধু)\s?(এর|য়ের|র) "
    r"(একাউন্ট|ব্যালেন্স|নম্বর)", r"onno (karo|kar|customer)",
    r"(?:^|\s)(bhai|bon|bou|jamai|baba|ma|bondhu)\s?(er|r) (account|balance|number)",
]
INTERNAL = [r"\bflag", r"suspicious", r"\bfraud", r"risk score", r"\bmy case\b",
            r"case (status|number|id)", r"watch ?list", r"blacklist", r"investigat", r"সন্দেহ",
            r"প্রতারণ", r"ফ্রড", r"কেসের", r"sondeh", r"protarona"]

ID_RE = re.compile(r"\b[UA]_[0-9_]{3,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(\+?880[\s-]?|\b0)1[3-9]\d[\s-]?\d{3}[\s-]?\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
LONG_DIGITS_RE = re.compile(r"\b\d{9,}\b")


@dataclass(frozen=True)
class Screen:
    kind: str  # ok | injection | secret | other_people | internal | too_long | empty
    detail: str = ""


def _hits(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return ""


def screen_input(text: str, own_ids: set[str]) -> Screen:
    clean = (text or "").strip()
    if not clean:
        return Screen("empty")
    if len(clean) > MAX_MESSAGE:
        return Screen("too_long")
    lowered = clean.lower()
    if hit := _hits(INJECTION, lowered):
        return Screen("injection", hit)
    foreign = {m.upper() for m in ID_RE.findall(clean)} - {i.upper() for i in own_ids}
    if foreign or PHONE_RE.search(clean.translate(BANGLA_DIGITS)):
        return Screen("other_people", "identifier")
    if hit := _hits(OTHER_PEOPLE, lowered):
        return Screen("other_people", hit)
    if hit := _hits(SECRETS, lowered):
        return Screen("secret", hit)
    if hit := _hits(INTERNAL, lowered):
        return Screen("internal", hit)
    return Screen("ok")


def redact(text: str, own_ids: set[str]) -> str:
    """Remove anything that identifies someone else, plus contact details."""
    own = {i.upper() for i in own_ids}

    def keep_own(match: re.Match) -> str:
        return match.group(0) if match.group(0).upper() in own else "[hidden]"

    out = ID_RE.sub(keep_own, text)
    if PHONE_RE.search(out.translate(BANGLA_DIGITS)):
        out = PHONE_RE.sub("[hidden]", out.translate(BANGLA_DIGITS))
    out = EMAIL_RE.sub("[hidden]", out)
    return LONG_DIGITS_RE.sub("[hidden]", out)


def numbers_in(text: str) -> set[float]:
    plain = text.translate(BANGLA_DIGITS).replace(",", "")
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", plain)}


def grounded(reply: str, allowed: set[float]) -> bool:
    """Every number in an AI reply must come from the customer's facts (or be a keypad key)."""
    keypad = {0.0, 1.0, 2.0, 7.0, 8.0, 9.0, 30.0}
    return all(n in allowed or n in keypad for n in numbers_in(reply))
