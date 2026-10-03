"""Comprehensive tests for keypad stated amount parser and normalizer."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from app.verification.keypad import (
    KeypadParseError,
    parse_keypad_amount,
    to_bangla_digits,
    to_western_digits,
)


def test_western_and_bangla_digits_conversion():
    assert to_bangla_digits(3000) == "৩,০০০"
    assert to_bangla_digits(45.5) == "৪৫.৫০"
    assert to_bangla_digits("12345") == "১২৩৪৫"
    assert to_western_digits("৩,০০০.৫০") == "3,000.50"
    assert to_western_digits("০১২৩৪৫৬৭৮৯") == "0123456789"


@pytest.mark.parametrize(
    "input_val, expected_dec",
    [
        (3000, Decimal("3000.00")),
        (3000.0, Decimal("3000.00")),
        ("3000", Decimal("3000.00")),
        ("3000.5", Decimal("3000.50")),
        ("3000.50", Decimal("3000.50")),
        ("3,000", Decimal("3000.00")),
        ("3,000.50", Decimal("3000.50")),
        ("1,00,000", Decimal("100000.00")),
        ("25,00,000", Decimal("2500000.00")),
        ("5,00,000.50", Decimal("500000.50")),
        ("৩৫০০", Decimal("3500.00")),
        ("৩,৫০০", Decimal("3500.00")),
        ("৩,৫০০.৭৫", Decimal("3500.75")),
        ("১,০০,০০০", Decimal("100000.00")),
        ("২৫,০০,০০০", Decimal("2500000.00")),
        (Decimal("4500.25"), Decimal("4500.25")),
    ],
)
def test_valid_numeric_amounts(input_val, expected_dec):
    result = parse_keypad_amount(input_val)
    assert result == expected_dec
    assert isinstance(result, Decimal)


@pytest.mark.parametrize(
    "bad_input",
    [
        True,
        False,
        None,
        "",
        "   ",
        float("nan"),
        float("inf"),
        float("-inf"),
        math.nan,
        math.inf,
        0,
        0.0,
        "0",
        "0.00",
        -100,
        -0.01,
        "-500",
        "-৩০০০",
        "100.555",  # Precision excess (> 2 decimal places)
        "৩৫০০.১২৩",  # Bangla precision excess
        "3000.00.00",  # Multiple decimal points
        ",3000",  # Leading comma
        "3000,",  # Trailing comma
        "3,,000",  # Consecutive commas
        "3,00,0",  # Misplaced comma with non-matching pattern
        "2,50",  # Malformed comma grouping
        "3000.0,5",  # Comma in fractional digits
        "3000; DROP TABLE mandates; --",  # SQL injection
        "1' OR '1'='1",  # SQL injection
        "<script>alert(1)</script>",  # Script injection
        "three thousand",  # English text
        "তিন হাজার",  # Bangla text
        "3000 BDT",  # Trailing currency
        "BDT 3000",  # Leading currency
        10000000000,  # Exceeding numeric(12,2)
    ],
)
def test_invalid_and_injection_inputs_rejected(bad_input):
    with pytest.raises(KeypadParseError):
        parse_keypad_amount(bad_input)
