"""Output and input guards for AI case briefs.

A cited fact ID only proves that the reference exists. It does not prove that the sentence is
supported by the fact. These guards add deterministic, pattern-level checks on EVERY text
field of a model-written brief, and they shrink what leaves the server in the first place.

What the guards do:
- Input: send an allowlist of typed evidence fields to an external model, never identifiers,
  timestamps, free-text case details or phone numbers.
- Output: reject secret requests (PIN, OTP, password), phone numbers, e-mail, links, internal
  identifiers, accusations and guilt certainty, spelled-out money amounts, any number that is
  not in the cited facts, claims that a completed cash-out was held or recovered, claims that
  amounts matched when the case says they did not, and customer questions that name the
  amount, the help signal or the case.
- Languages: English, Bangla script and Banglish (romanised Bangla).

What they do NOT do: prove that a sentence means what its cited fact means. Pattern checks
cannot do that. A brief that passes is labelled "AI-written, pattern-checked". The
deterministic template (`template_brief`) is built from typed fields and is the default for a
public deployment (`SATHI_DEPLOYMENT_MODE=public_demo`).
"""

from __future__ import annotations

import re
from typing import Any

from app.assistant.guard import (
    BANGLA_DIGITS,
    EMAIL_RE,
    LONG_DIGITS_RE,
    PHONE_RE,
    SECRETS,
    numbers_in,
)

# Internal customer/agent identifiers, including registered test accounts (A_P_<number>).
ID_RE = re.compile(r"\b[UA]_(?:P_)?\d[\d_]{2,}\b", re.IGNORECASE)


class BriefGuardError(ValueError):
    """The brief text was rejected by a deterministic guard. The message names the guard."""


# ------------------------------------------------------------------ input minimisation
# Only these fact fields may be sent to an external model. Everything else (agent and
# transaction identifiers, timestamps, free-text case details) stays on the server.
EXTERNAL_FIELDS = re.compile(
    r"^(case\.(reason|status)"
    r"|mandate\.(status|verification_attempts|redemption_attempts|requested_amount_bdt)"
    r"|risk\.(band|step_up|score)"
    r"|risk\.reasons\[\d+\]\.explanation"
    r"|verification_events\[\d+\]\.(mode|outcome|stated_amount|cash_reported)"
    r"|calls\[\d+\]\.(provider|status|digit_attempts)"
    r"|transaction\.(ledger_amount_bdt|customer_typed_bdt|call_outcome|attempts)"
    r"|ai_recommendation\.label"
    r"|agent\.(cases_7d|open_cases_7d))$"
)


def redact_value(value: Any) -> Any:
    """Mask phone numbers, e-mail, internal IDs and long digit runs inside a string value."""
    if not isinstance(value, str):
        return value
    out = ID_RE.sub("[hidden]", value)
    out = PHONE_RE.sub("[hidden]", out.translate(BANGLA_DIGITS))
    out = EMAIL_RE.sub("[hidden]", out)
    return LONG_DIGITS_RE.sub("[hidden]", out)


def external_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The minimised subset of facts an external model may see. Fact IDs are unchanged."""
    return [{**fact, "value": redact_value(fact["value"])}
            for fact in facts if EXTERNAL_FIELDS.match(fact["field"])]


# ------------------------------------------------------------------ output patterns
_ACCUSATION = re.compile(
    r"\b(stole|stolen|steal|steals|stealing|theft|thief|thieves|rob|robs|robbed|robbery|"
    r"cheat|cheats|cheated|cheating|fraudster|fraudsters|fraudulent|defraud|defrauded|"
    r"embezzle\w*|skim|skims|skimmed|skimming|scammer|scammed|criminal\w*|guilty|culprit|"
    r"liar|lied|lying|dishonest|corrupt\w*|misappropriat\w*|extort\w*|collu\w+|conspir\w+|"
    r"chor|churi|chuiri|protarok|protarona|jaliyat|dosi|dushi|oporadhi|mithyabadi|"
    r"thokiyeche|thokaise|atmosat)\b"
    r"|চোর|চুরি|প্রতারক|প্রতারণা|জালিয়াত|অপরাধী|দোষী|মিথ্যাবাদী|ঠকিয়েছ|আত্মসাৎ|লুট|ঘুষ",
    re.IGNORECASE)
_CERTAINTY = re.compile(
    r"\b(confirmed|proven|definite|definitely|certain|certainly|clear|clearly|obvious|"
    r"obviously)\s+(is\s+|was\s+)?(fraud|theft|skimming|scam|misconduct|guilt|guilty)\b"
    r"|\b(is|was|are|were)\s+(definitely|certainly|clearly|obviously|undoubtedly)\b"
    r"|\b(undoubtedly|without (a )?doubt|no doubt|guaranteed|beyond doubt)\b"
    r"|নিশ্চিতভাবে|সন্দেহাতীত|প্রমাণিত",
    re.IGNORECASE)
_SECRET_EXTRA = [r"secret (code|number)", r"\bcvv\b", r"nid number", r"গোপন কোড", r"ওয়ান[- ]?টাইম",
                 r"\b(share|send|tell|give|read out|provide|say|dao|bolun|den)\b[^.?!]{0,40}"
                 r"\b(code|one[- ]time|kod)\b"]
_LINK = re.compile(r"https?://|www\.|\b[\w-]+\.(com|net|org|bd|io|co)\b", re.IGNORECASE)
_MONEY_WORDS = re.compile(
    r"\b(hundred|thousand|lakh|lac|crore|hajar|hazar|hajaar|shoto|lakkho|koti)\b"
    r"|হাজার|লাখ|লক্ষ|কোটি|শত\b|শো\b",
    re.IGNORECASE)
# A completed cash-out is a fact. This tool detects and supports resolution; it did not hold,
# block, prevent or recover that money.
_PREVENTION = re.compile(
    r"\b(held|hold|holding|blocked|blocking|stopped|prevented|withheld|frozen|freeze|"
    r"cancel(l)?ed|reversed|refunded|recovered|returned|rolled back)\b"
    r"|আটকে|আটক|ব্লক|ফেরত|স্থগিত|প্রতিরোধ",
    re.IGNORECASE)
_NEGATION = re.compile(r"\b(not|no|never|without|didn't|did not|don't|cannot|can't|hasn't)\b|না\b",
                       re.IGNORECASE)
_MATCH_CLAIM = re.compile(
    r"\b(amounts? (did |does |do )?match(ed|es)?|matched|(amount|cash) (was |is )?(confirmed|"
    r"verified|correct)|(confirmed|verified) the (amount|cash)|consistent with the ledger)\b",
    re.IGNORECASE)
_CUSTOMER_DISCLOSURE = re.compile(
    r"\b(duress|secret|help signal|flag(ged)?|suspicious|suspect\w*|fraud\w*|case|watch ?list|"
    r"risk score|investigat\w+|agent (is|was|has))\b|বিপদ সংকেত|সন্দেহ|ফ্রড|কেস",
    re.IGNORECASE)

MISMATCH_FAMILY = {"stated_amount_mismatch", "post_txn_amount_mismatch", "customer_denied_request",
                   "customer_denied_transaction", "duress_signal", "cash_gap_tolerance_exceeded"}
CLOSE_ALLOWED_REASONS = {"stated_amount_mismatch", "post_txn_amount_mismatch"}


def fact_numbers(facts: list[dict[str, Any]]) -> set[float]:
    """Every number that appears in the given facts (digits in strings included)."""
    allowed: set[float] = set()
    for fact in facts:
        value = fact["value"]
        if isinstance(value, bool) or value is None:
            continue
        allowed |= numbers_in(str(value))
    return allowed


def _fail(field: str, rule: str) -> BriefGuardError:
    return BriefGuardError(f"{field}: {rule}")


def check_text(text: str, field: str, allowed: set[float], *,
               evidence: dict[str, Any] | None = None, customer_facing: bool = False) -> None:
    """Raise BriefGuardError when one text field breaks a rule. `allowed` holds the numbers
    this field may mention; a customer-facing question may mention none."""
    flat = text.translate(BANGLA_DIGITS)
    lowered = flat.lower()
    for pattern in [*SECRETS, *_SECRET_EXTRA]:
        if re.search(pattern, lowered, re.IGNORECASE):
            raise _fail(field, "asks for or mentions a secret (PIN, OTP, password)")
    if PHONE_RE.search(flat) or LONG_DIGITS_RE.search(flat):
        raise _fail(field, "contains a phone number or long digit run")
    if EMAIL_RE.search(flat) or _LINK.search(flat):
        raise _fail(field, "contains an e-mail address or link")
    if ID_RE.search(flat):
        raise _fail(field, "contains an internal identifier")
    if _ACCUSATION.search(flat):
        raise _fail(field, "contains an accusation or an unsupported legal conclusion")
    if _CERTAINTY.search(flat):
        raise _fail(field, "claims certainty about misconduct")
    if _MONEY_WORDS.search(flat):
        raise _fail(field, "spells out a money amount")
    used = numbers_in(flat)
    if customer_facing and used:
        raise _fail(field, "a customer question must not contain an amount or number")
    if not used <= allowed:
        raise _fail(field, "contains a number that is not in the cited facts")
    if evidence is not None:
        reason = str(evidence.get("case", {}).get("reason", ""))
        if "transaction" in evidence and _PREVENTION.search(flat):
            raise _fail(field, "says the completed cash-out was held, stopped or recovered")
        if "mandate" not in evidence and re.search(r"mandate|ম্যান্ডেট", flat, re.IGNORECASE):
            raise _fail(field, "mentions a mandate but the evidence has none")
        if reason in MISMATCH_FAMILY:
            for match in _MATCH_CLAIM.finditer(lowered):
                before = lowered[max(0, match.start() - 24):match.start()]
                if not _NEGATION.search(before) and not _NEGATION.search(match.group(0)):
                    raise _fail(field, "claims the amounts matched but the case says they did not")
    if customer_facing and _CUSTOMER_DISCLOSURE.search(flat):
        raise _fail(field, "a customer question must not reveal flags, the case or the help signal")


def check_brief(brief: dict[str, Any], facts: list[dict[str, Any]],
                evidence: dict[str, Any] | None = None) -> None:
    """Guard every text field of a structurally valid brief.

    Narrative fields may use any number present in the facts. A `why_risky` point may only use
    numbers from the facts it cites, so a figure cannot be attached to the wrong evidence.
    """
    by_id = {fact["id"]: fact for fact in facts}
    allowed_all = fact_numbers(facts)
    for field in ("headline", "what_happened", "summary_bn"):
        check_text(brief[field], field, allowed_all, evidence=evidence)
    for index, item in enumerate(brief["why_risky"]):
        allowed = fact_numbers([by_id[c] for c in item["evidence"]])
        check_text(item["point"], f"why_risky[{index}]", allowed, evidence=evidence)
    for index, question in enumerate(brief["questions_for_customer"]):
        check_text(question, f"questions_for_customer[{index}]", set(), evidence=evidence,
                   customer_facing=True)
    if evidence is not None:
        reason = str(evidence.get("case", {}).get("reason", ""))
        if brief["recommended_next_step"] == "close_as_customer_error" \
                and reason not in CLOSE_ALLOWED_REASONS:
            raise _fail("recommended_next_step",
                        "closing as a customer error is not allowed for this case reason")
