"""Receipt generation and numerical integrity verification for Sathi.

Conforms to docs/architecture.md and docs/api-contracts.md:
- Generates plain-language Bangla receipt text from structured runtime records.
- Enforces strict post-check: compares all numbers in the generated text against
  runtime transaction values to prevent numerical hallucination.
"""

from __future__ import annotations

import re
from typing import Any

# Bengali to Western digit translation table
BN_TO_EN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
EN_TO_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def to_bangla_digits(val: int | float | str) -> str:
    """Convert integer or float into Bangla digits with comma grouping."""
    if isinstance(val, (int, float)):
        # Format with comma separators
        if isinstance(val, float) and not val.is_integer():
            formatted = f"{val:,.2f}"
        else:
            formatted = f"{int(val):,}"
    else:
        formatted = str(val)
    return formatted.translate(EN_TO_BN_DIGITS)


def to_western_digits(text: str) -> str:
    """Convert Bangla digits in text to Western digits."""
    return text.translate(BN_TO_EN_DIGITS)


def extract_numbers_from_text(text: str) -> list[float]:
    """Extract all numeric quantities from text, normalizing Bengali numerals."""
    westernized = to_western_digits(text)
    # Remove commas between digits e.g. 3,000 -> 3000
    normalized = re.sub(r"(?<=\d),(?=\d)", "", westernized)
    # Find all float or integer patterns
    matches = re.findall(r"\b\d+(?:\.\d+)?\b", normalized)
    return [float(m) for m in matches]


class ReceiptValidationError(Exception):
    """Raised when generated receipt text contains inaccurate or altered numbers."""

    def __init__(self, message: str):
        super().__init__(message)


def validate_receipt_numerical_integrity(
    receipt_text: str,
    expected_numbers: set[float] | list[float],
) -> bool:
    """Validate that all expected numbers exist within the receipt text
    and no unexpected numbers are present.

    Raises ReceiptValidationError if any expected number is missing or altered,
    or if any unexpected numeric token is found in the receipt text.
    Preserves exact cents precision.
    """
    extracted_nums = extract_numbers_from_text(receipt_text)
    expected_list = [float(e) for e in expected_numbers]

    for expected in expected_list:
        if not any(abs(extracted - expected) < 0.005 for extracted in extracted_nums):
            msg = (
                f"Generated receipt failed numerical check: "
                f"expected number {expected} missing from text."
            )
            raise ReceiptValidationError(msg)

    for extracted in extracted_nums:
        if not any(abs(extracted - expected) < 0.005 for expected in expected_list):
            msg = (
                f"Generated receipt failed numerical check: "
                f"unexpected number {extracted} found in text."
            )
            raise ReceiptValidationError(msg)

    return True


def generate_bangla_receipt(
    txn_id: int,
    user_id: str,
    agent_id: str,
    amount_bdt: float,
    fee_bdt: float,
    payout_bdt: float,
    ts_iso: str,
) -> dict[str, Any]:
    """Generate verified Bangla receipt text from structured transaction values.

    Validates that numbers in receipt text strictly match the runtime mandate values.
    """
    amt_bn = to_bangla_digits(int(amount_bdt) if amount_bdt.is_integer() else amount_bdt)
    fee_bn = to_bangla_digits(int(fee_bdt) if fee_bdt.is_integer() else fee_bdt)
    payout_bn = to_bangla_digits(int(payout_bdt) if payout_bdt.is_integer() else payout_bdt)
    txn_bn = to_bangla_digits(txn_id)

    receipt_text = (
        f"সাথী ক্যাশ-আউট সফল হয়েছে। "
        f"উত্তোলন: {amt_bn} টাকা, ফি: {fee_bn} টাকা, প্রাপ্ত অর্থ: {payout_bn} টাকা। "
        f"এজেন্ট: {agent_id}, ট্রানজ্যাকশন আইডি: {txn_bn}।"
    )

    # Post-check: numerical integrity verification
    expected_nums = {
        float(amount_bdt),
        float(fee_bdt),
        float(payout_bdt),
        float(txn_id),
    }
    validate_receipt_numerical_integrity(receipt_text, expected_nums)

    return {
        "txn_id": txn_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "amount_bdt": float(amount_bdt),
        "fee_bdt": float(fee_bdt),
        "payout_bdt": float(payout_bdt),
        "ts": ts_iso,
        "receipt_text_bn": receipt_text,
        "verification_status": "verified",
        "provenance": "runtime memory, not a database record",
    }
