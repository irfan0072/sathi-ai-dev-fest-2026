"""Understand a customer's answer on the confirmation call.

Answers arrive as keypad digits (DTMF) or, on providers with speech recognition, as a
transcript with a confidence score. Anything the system cannot read with confidence is
"unclear": it is never guessed. Unclear answers are re-asked once and then handed to a
human supervisor, who calls the customer back.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_AMOUNT_DIGITS = 7  # ৳9,999,999 is far above any single cash-out cap
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

_EN_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
# Bangla number words in Bengali script and in Banglish (romanized) spellings.
_BN_UNITS = {
    "এক": 1, "দুই": 2, "দু": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "সাত": 7,
    "আট": 8, "নয়": 9, "দশ": 10, "এগারো": 11, "বারো": 12, "তেরো": 13, "চোদ্দ": 14,
    "পনেরো": 15, "ষোলো": 16, "সতেরো": 17, "আঠারো": 18, "উনিশ": 19, "বিশ": 20, "কুড়ি": 20,
    "পঁচিশ": 25, "ত্রিশ": 30, "চল্লিশ": 40, "পঞ্চাশ": 50, "ষাট": 60, "সত্তর": 70, "আশি": 80,
    "নব্বই": 90,
    "ek": 1, "dui": 2, "du": 2, "tin": 3, "teen": 3, "char": 4, "pach": 5, "panch": 5,
    "choy": 6, "chhoy": 6, "chhoi": 6, "sat": 7, "saat": 7, "at": 8, "aat": 8, "noy": 9,
    "dosh": 10, "dos": 10, "egaro": 11, "baro": 12, "tero": 13, "choddo": 14, "ponero": 15,
    "sholo": 16, "shotero": 17, "atharo": 18, "unish": 19, "bish": 20, "kuri": 20,
    "pochish": 25, "trish": 30, "tirish": 30, "chollish": 40, "ponchash": 50,
    "panchash": 50, "shat": 60, "sottor": 70, "ashi": 80, "nobboi": 90,
}
# "দেড়" = one and a half, "আড়াই" = two and a half (very common in spoken amounts).
_FRACTIONS = {"দেড়": 1.5, "আড়াই": 2.5, "der": 1.5, "dedh": 1.5, "deṛ": 1.5,
              "arai": 2.5, "adai": 2.5, "araai": 2.5}
# "সাড়ে তিন হাজার" = three and a half thousand.
_HALF_MORE = {"সাড়ে", "sare", "sharhe", "saare", "sarhe"}
_EN_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "lac": 100_000,
              "k": 1000}
_BN_SCALES = {"শ": 100, "শো": 100, "শত": 100, "হাজার": 1000, "লাখ": 100_000, "লক্ষ": 100_000,
              "sho": 100, "shoto": 100, "so": 100, "hajar": 1000, "hazar": 1000,
              "hajaar": 1000}
_FILLER = {"and", "taka", "tk", "টাকা", "takar", "bdt", "only", "matro", "মাত্র", "ami",
           "আমি", "peyechi", "পেয়েছি", "paisi", "pelam", "got", "received", "i",
           "hate", "হাতে", "approximately", "prai", "প্রায়", "রুপি"}
_DENY_PHRASES = ("did not", "didn't", "didnt", "not me", "never did", "korini", "kori nai",
                 "korinai", "করিনি", "করি নাই", "আমি না", "ami na ", "tola hoyni", "tulini",
                 "তুলিনি", "তুলি নাই")


@dataclass(frozen=True)
class Answer:
    kind: str  # amount | denied | unclear
    digits: str = ""
    confidence: float | None = None
    raw: str = ""


def _words_to_number(text: str) -> int | None:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*k\b", lambda m: str(int(float(m.group(1)) * 1000)),
                  text.lower())
    tokens = re.findall(r"[a-z']+|[\u0980-\u09FF]+|\d+(?:\.\d+)?", text)
    if not tokens:
        return None
    total, current, seen, half = 0.0, 0.0, False, False
    for tok in tokens:
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            current += float(tok)
            seen = True
        elif tok in _EN_UNITS or tok in _BN_UNITS:
            current += _EN_UNITS.get(tok, _BN_UNITS.get(tok, 0))
            seen = True
        elif tok in _FRACTIONS:
            current += _FRACTIONS[tok]
            seen = True
        elif tok in _HALF_MORE:
            half = True
        elif tok in _EN_SCALES or tok in _BN_SCALES:
            scale = _EN_SCALES.get(tok, _BN_SCALES.get(tok, 1))
            current = (max(current, 1) + (0.5 if half else 0)) * scale
            half = False
            if scale >= 1000:
                total += current
                current = 0
            seen = True
        elif tok in _FILLER:
            continue
        else:
            return None
    value = total + current
    if not seen or value != value or value <= 0 or abs(value - round(value)) > 1e-6:
        return None
    return int(round(value))


def interpret(digits: str | None, speech: str | None = None,
              confidence: float | None = None, min_confidence: float = 0.6) -> Answer:
    raw = (digits or "").strip()
    if raw:
        if re.search(r"[^0-9#]", raw):
            return Answer("unclear", raw=raw)
        keys = raw.replace("#", "")
        if keys == "":
            return Answer("denied", raw=raw)
        if len(keys) > MAX_AMOUNT_DIGITS + 1 or int(keys) == 0:
            return Answer("unclear", raw=raw)
        return Answer("amount", digits=keys, raw=raw)

    text = (speech or "").strip()
    if not text:
        # "#" alone (empty digits, no speech) means "I did not do this".
        return Answer("denied", raw="")
    if confidence is not None and confidence < min_confidence:
        return Answer("unclear", confidence=confidence, raw=text)
    normalized = unicodedata.normalize("NFC", text).translate(BANGLA_DIGITS)
    lowered = normalized.lower()
    # Denial needs an explicit phrase ("I did not do it"). A bare "no"/"na" is ambiguous
    # (it often means "I don't understand"), so it is treated as unclear, never as denial.
    if any(p in lowered for p in _DENY_PHRASES) and not re.search(r"\d", normalized):
        return Answer("denied", confidence=confidence, raw=text)
    compact = re.sub(r"[\s,]|taka|tk|টাকা", "", normalized.lower())
    if re.fullmatch(r"\d{1,8}", compact):
        value = compact
    else:
        number = _words_to_number(normalized)
        value = str(number) if number else ""
    if not value or int(value) == 0 or len(value.lstrip("0")) > MAX_AMOUNT_DIGITS:
        return Answer("unclear", confidence=confidence, raw=text)
    return Answer("amount", digits=value, confidence=confidence, raw=text)
