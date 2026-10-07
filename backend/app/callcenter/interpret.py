"""Understand a customer's answer on the confirmation call.

Answers arrive as keypad digits (DTMF) or, on providers with speech recognition, as a
transcript with a confidence score. Anything the system cannot read with confidence is
"unclear": it is never guessed. Unclear answers are re-asked once and then handed to a
human supervisor, who calls the customer back.

This module is a parser that runs AFTER a provider has transcribed the audio. It is not an
ASR model and it never listens to audio. Safety policy for spoken answers:

- The transcript must be text and the confidence must be a finite number in [0, 1].
- A missing confidence is not invented. The provider does not guarantee one, so a spoken
  answer without a usable confidence is "unclear" and goes to keypad confirmation or a
  person (`MISSING_CONFIDENCE_POLICY`). Keypad digits never need a confidence.
- Approximate ("about three thousand"), alternative ("three or four thousand") and
  conflicting ("three thousand five thousand") amounts are "unclear", never exact.
- Silence and empty callbacks are handled before this module and are never a denial. Denial is
  explicit: "*" on the keypad, or a clear spoken phrase.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MAX_AMOUNT_DIGITS = 7  # ৳9,999,999 is far above any single cash-out cap
MAX_TRANSCRIPT_CHARS = 200
MISSING_CONFIDENCE_POLICY = "unclear"  # spoken answer with no usable confidence: ask for keypad
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
           "hate", "হাতে", "রুপি"}
# Words that make an amount inexact, hedged or ambiguous. They are never filler: the answer
# is "unclear" and the customer confirms on the keypad instead.
_APPROXIMATE = {
    "approximately", "approx", "about", "around", "roughly", "nearly", "almost", "maybe",
    "perhaps", "probably", "guess", "think", "over", "under", "above", "below", "less",
    "more", "least", "most", "than", "prai", "প্রায়", "mota", "motamuti", "মোটামুটি",
    "kachakachi", "কাছাকাছি", "onuman", "anumanik", "অনুমান", "আনুমানিক", "kom", "কম",
    "beshi", "bhesi", "বেশি", "mone", "মনে",
}
_ALTERNATIVE = {"or", "either", "between", "ba", "বা", "naki", "নাকি", "othoba", "অথবা",
                "theke", "থেকে", "to"}
_DENY_PHRASES = ("did not", "didn't", "didnt", "not me", "never did", "korini", "kori nai",
                 "korinai", "করিনি", "করি নাই", "আমি না", "ami na ", "tola hoyni", "tulini",
                 "তুলিনি", "তুলি নাই")


@dataclass(frozen=True)
class Answer:
    kind: str  # amount | denied | unclear
    digits: str = ""
    confidence: float | None = None
    raw: str = ""
    reason: str = ""  # why an answer is "unclear" (empty for amount/denied)


def clean_confidence(value: Any) -> tuple[float | None, str]:
    """Return (confidence, status). Status is "ok", "missing" or "invalid".

    Only a real number (or numeric string) that is finite and within [0, 1] is "ok". Booleans,
    NaN, infinity, out-of-range values and other types are "invalid", never coerced.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    if isinstance(value, bool):
        return None, "invalid"
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None, "invalid"
    else:
        return None, "invalid"
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None, "invalid"
    return number, "ok"


def _lowest_place(value: float) -> int:
    """Largest power of ten that divides `value` (3500 -> 100, 3000 -> 1000, 7 -> 1)."""
    whole = int(round(value))
    if whole <= 0 or abs(value - whole) > 1e-9:
        return 0
    place = 1
    while whole % (place * 10) == 0:
        place *= 10
    return place


def _can_append(existing: float, addition: float) -> bool:
    """A number may only be extended by something smaller than its lowest place: twenty +
    five is fine, twenty + thirty and three thousand + five thousand are conflicts."""
    place = _lowest_place(existing)
    return place > 0 and 0 < addition < place


def _words_to_number(text: str) -> int | None:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*k\b", lambda m: str(int(float(m.group(1)) * 1000)),
                  text.lower())
    tokens = re.findall(r"[a-z']+|[\u0980-\u09FF]+|\d+(?:\.\d+)?", text)
    if not tokens:
        return None
    total, current, seen, half = 0.0, 0.0, False, False
    last_big = float("inf")
    for tok in tokens:
        is_number = re.fullmatch(r"\d+(?:\.\d+)?", tok) is not None
        if is_number or tok in _EN_UNITS or tok in _BN_UNITS or tok in _FRACTIONS:
            if is_number:
                part = float(tok)
            elif tok in _FRACTIONS:
                part = _FRACTIONS[tok]
            else:
                part = _EN_UNITS.get(tok, _BN_UNITS.get(tok, 0))
            if current > 0 and not _can_append(current, part):
                return None  # two separate amounts, e.g. "twenty thirty" or "3000 5000"
            current += part
            seen = True
        elif tok in _HALF_MORE:
            half = True
        elif tok in _EN_SCALES or tok in _BN_SCALES:
            scale = _EN_SCALES.get(tok, _BN_SCALES.get(tok, 1))
            if scale >= 1000:
                if scale >= last_big:
                    return None  # "three thousand five thousand", "thousand ... lakh"
                group = (max(current, 1) + (0.5 if half else 0)) * scale
                if total > 0 and not _can_append(total, group):
                    return None
                total += group
                current, last_big = 0, scale
            else:
                if current >= 100:
                    return None
                current = (max(current, 1) + (0.5 if half else 0)) * scale
            half = False
            seen = True
        elif tok in _FILLER:
            continue
        else:
            return None
    if total > 0 and current > 0 and not _can_append(total, current):
        return None
    value = total + current
    if not seen or value != value or value <= 0 or abs(value - round(value)) > 1e-6:
        return None
    return int(round(value))


_COMMA_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+|\d{1,3}(?:,\d{2})*,\d{3}")


def _plain_numerals(text: str) -> list[str] | None:
    """Digit groups when the text is only numerals (and money words); None for other text."""
    stripped = re.sub(r"\b(?:taka|tk|bdt)\b|টাকা|৳", " ", text)
    pieces = stripped.split()
    if not pieces:
        return None
    groups = []
    for piece in pieces:
        piece = piece.strip(",")
        if re.fullmatch(r"\d+", piece):
            groups.append(piece)
        elif _COMMA_GROUPED.fullmatch(piece):
            groups.append(piece.replace(",", ""))
        elif "," in piece and re.fullmatch(r"[\d,]+", piece):
            groups.extend(["?", "?"])  # malformed grouping: treated as conflicting numerals
        else:
            return None
    return groups


def interpret(digits: Any, speech: Any = None, confidence: Any = None,
              min_confidence: float = 0.6) -> Answer:
    if digits is not None and not isinstance(digits, str):
        return Answer("unclear", reason="invalid_input")
    if speech is not None and not isinstance(speech, str):
        return Answer("unclear", reason="invalid_input")
    raw = (digits or "").strip()
    if raw:
        # "*" alone is the explicit keypad denial ("I did not make this cash-out"). A bare
        # "#" (finish key with nothing typed) is an empty answer, never a denial.
        if raw.replace("#", "") == "*":
            return Answer("denied", raw=raw)
        if re.search(r"[^0-9#]", raw):
            return Answer("unclear", raw=raw, reason="invalid_keys")
        keys = raw.replace("#", "")
        if keys == "":
            return Answer("unclear", raw=raw, reason="empty_input")
        if len(keys) > MAX_AMOUNT_DIGITS + 1 or int(keys) == 0:
            return Answer("unclear", raw=raw, reason="out_of_range")
        return Answer("amount", digits=keys, raw=raw)

    text = (speech or "").strip()
    if not text:
        # Nothing was typed or said: silence or a timeout. Never a denial or a confirmation.
        return Answer("unclear", raw="", reason="empty_input")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        return Answer("unclear", raw=text[:MAX_TRANSCRIPT_CHARS], reason="too_long")
    score, status = clean_confidence(confidence)
    if status == "invalid":
        return Answer("unclear", raw=text, reason="invalid_confidence")
    if status == "missing":
        return Answer("unclear", raw=text, reason="confidence_missing")  # policy: keypad
    if score < min_confidence:
        return Answer("unclear", confidence=score, raw=text, reason="low_confidence")
    confidence = score
    normalized = unicodedata.normalize("NFC", text).translate(BANGLA_DIGITS)
    lowered = normalized.lower()
    # Denial needs an explicit phrase ("I did not do it"). A bare "no"/"na" is ambiguous
    # (it often means "I don't understand"), so it is treated as unclear, never as denial.
    if any(p in lowered for p in _DENY_PHRASES) and not re.search(r"\d", normalized):
        return Answer("denied", confidence=confidence, raw=text)
    words = set(re.findall(r"[a-z']+|[\u0980-\u09FF]+", lowered))
    if words & _APPROXIMATE or re.search(r"[~≈<>±]", lowered):
        return Answer("unclear", confidence=confidence, raw=text, reason="approximate")
    if words & _ALTERNATIVE:
        return Answer("unclear", confidence=confidence, raw=text, reason="conflicting_amounts")
    groups = _plain_numerals(lowered)
    if groups is not None:
        if len(groups) == 2 and groups[0] == "0":
            groups = ["".join(groups)]  # "0 3000": the silent help signal, spoken as digits
        if len(groups) != 1:
            return Answer("unclear", confidence=confidence, raw=text,
                          reason="conflicting_amounts")
        value = groups[0]
        if len(value) > 8:
            return Answer("unclear", confidence=confidence, raw=text, reason="out_of_range")
    else:
        number = _words_to_number(normalized)
        value = str(number) if number else ""
    if not value or int(value) == 0 or len(value.lstrip("0")) > MAX_AMOUNT_DIGITS:
        return Answer("unclear", confidence=confidence, raw=text, reason="unparseable")
    return Answer("amount", digits=value, confidence=confidence, raw=text)
