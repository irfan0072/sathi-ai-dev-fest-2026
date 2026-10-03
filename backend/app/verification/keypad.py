"""Keypad stated amount parsing and normalization for Sathi.

Normalizes Bangla numerals and comma grouping, accepts finite positive
numeric text and JSON numbers with at most 2 decimal places, and strictly
rejects ambiguous input, free-text injection, booleans, NaN/Infinity,
negative amounts, and precision excess.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

# Translation tables between Western and Bengali numerals
BN_TO_EN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
EN_TO_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


class KeypadParseError(ValueError):
    """Raised when stated amount cannot be safely parsed into positive Decimal cents."""


def to_western_digits(text: str) -> str:
    """Convert Bengali numerals in string to standard Western ASCII digits."""
    return text.translate(BN_TO_EN_DIGITS)


def to_bangla_digits(val: int | float | str | Decimal) -> str:
    """Convert number or text into Bengali numerals."""
    if isinstance(val, (int, float, Decimal)):
        if isinstance(val, float) and not val.is_integer():
            formatted = f"{val:,.2f}"
        elif isinstance(val, Decimal):
            formatted = f"{val:,.2f}" if val.as_tuple().exponent < 0 else f"{int(val):,}"
        else:
            formatted = f"{int(val):,}"
    else:
        formatted = str(val)
    return formatted.translate(EN_TO_BN_DIGITS)


# Strict comma grouping regexes for integer part
WESTERN_GROUPING = re.compile(r"^\d{1,3}(,\d{3})+$")
BANGLADESH_GROUPING = re.compile(r"^\d{1,2}(,\d{2})*,\d{3}$")


def parse_keypad_amount(val: Any) -> Decimal:
    """Safely parse stated amount from keypad or voice transcript into Decimal cents.

    Requirements:
    - Rejects booleans explicitly (bool inherits from int in Python).
    - Rejects None, NaN, positive/negative Infinity.
    - Normalizes Bengali numerals (০-৯ -> 0-9).
    - Validates Western and Bangladesh lakh comma grouping explicitly.
    - Strictly rejects malformed comma groupings (e.g. '3,00,0', '2,50', '3000.0,5').
    - Accepts finite positive numbers with <= 2 decimal places.
    - Rejects free-text, SQL injection, multiple decimal points, trailing non-digits.
    - Strictly rejects non-positive (<= 0) numbers.
    - Returns Decimal quantized to 0.01.
    """
    if isinstance(val, bool):
        raise KeypadParseError("Boolean values are not accepted as numeric amounts.")

    if val is None:
        raise KeypadParseError("Stated amount cannot be null or empty.")

    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            raise KeypadParseError("NaN and Infinity are not accepted.")
        val_str = str(val)
    elif isinstance(val, str):
        val_str = val.strip()
        if not val_str:
            raise KeypadParseError("Stated amount string cannot be empty.")
    elif isinstance(val, Decimal):
        if not val.is_finite():
            raise KeypadParseError("Non-finite Decimal is not accepted.")
        val_str = str(val)
    else:
        raise KeypadParseError(f"Unsupported data type for stated amount: {type(val).__name__}")

    # Convert Bangla digits to Western digits
    val_str = to_western_digits(val_str)

    # Check for decimal split
    if "." in val_str:
        parts = val_str.split(".")
        if len(parts) != 2:
            raise KeypadParseError("Multiple decimal points in stated amount.")
        int_part, frac_part = parts[0], parts[1]
        # Commas in fractional digits are strictly forbidden
        if "," in frac_part:
            raise KeypadParseError("Commas are not permitted in fractional digits.")
        if not re.match(r"^\d+$", frac_part):
            raise KeypadParseError(f"Ambiguous or invalid fractional digits: '{frac_part}'")
        if len(frac_part) > 2:
            raise KeypadParseError("Precision excess: maximum 2 decimal places allowed.")
    else:
        int_part = val_str
        frac_part = None

    if not int_part:
        raise KeypadParseError("Missing integer digits in stated amount.")

    # Validate integer part comma grouping
    if "," in int_part:
        if int_part.startswith(",") or int_part.endswith(",") or ",," in int_part:
            raise KeypadParseError("Invalid comma formatting in stated amount.")
        if not (WESTERN_GROUPING.match(int_part) or BANGLADESH_GROUPING.match(int_part)):
            raise KeypadParseError(f"Malformed comma grouping in stated amount: '{int_part}'")
        clean_int = int_part.replace(",", "")
    else:
        if not re.match(r"^\d+$", int_part):
            raise KeypadParseError(f"Ambiguous or invalid numeric text: '{int_part}'")
        clean_int = int_part

    clean_str = clean_int + (f".{frac_part}" if frac_part is not None else "")

    try:
        dec = Decimal(clean_str)
    except InvalidOperation as exc:
        raise KeypadParseError(f"Invalid decimal representation: '{clean_str}'") from exc

    if not dec.is_finite():
        raise KeypadParseError("Amount must be finite.")

    if dec <= Decimal("0"):
        raise KeypadParseError("Amount must be strictly positive.")

    # Check precision: at most 2 decimal places
    exp = dec.as_tuple().exponent
    if isinstance(exp, int) and exp < -2:
        raise KeypadParseError("Precision excess: maximum 2 decimal places allowed.")

    if dec >= Decimal("10000000000"):
        raise KeypadParseError("Amount exceeds maximum allowed limit.")

    return dec.quantize(Decimal("0.01"))
