"""Feature leakage guard and column allowlist enforcement for Sathi.

Ensures that protected attributes, ground-truth simulation labels,
raw ledger ground truths, and identifiers are strictly excluded from
feature matrices before any modeling.
"""

from collections.abc import Iterable
from typing import Any


class FeatureLeakageError(ValueError):
    """Raised when forbidden columns or unapproved features are detected."""


# Explicit allowlist of approved numeric behavioral features
ALLOWED_NUMERIC_BEHAVIORAL_FEATURES: frozenset[str] = frozenset(
    {
        "top_agent_share",
        "top_agent_concentration",
        "cash_out_tx_count",
        "cash_out_total_amount",
        "cash_out_amount_mean",
        "cash_out_amount_median",
        "cash_out_amount_std",
        "cash_out_amount_min",
        "cash_out_amount_max",
        "credit_tx_count",
        "credit_total_amount",
        "credit_amount_mean",
        "credit_to_cashout_hours_mean",
        "credit_to_cashout_hours_min",
        "credit_to_cashout_hours_median",
        "withdrawn_balance_ratio_mean",
        "withdrawn_balance_ratio_max",
        "balance_end",
        "balance_mean",
        "balance_min",
        "pin_retries_total",
        "pin_retries_mean",
        "pin_retries_max",
        "pin_entry_seconds_mean",
        "pin_entry_seconds_median",
        "pin_entry_seconds_std",
        "session_steps_mean",
        "session_steps_max",
        "service_diversity_count",
        "send_tx_count",
        "send_total_amount",
        "bill_pay_tx_count",
        "bill_pay_total_amount",
        "agent_assisted_tx_ratio",
        "fee_total_paid",
        "fee_to_amount_ratio",
        "cash_gap_reported_count",
        "cash_gap_reported_total",
        "agent_cash_report_count",
        "agent_cash_report_coverage",
        "agent_cash_gap_missing",
        "agent_cash_gap_has_reports",
        "agent_fee_ratio_over_official",
        "agent_volume_daily_mean",
        "agent_allowance_day_volume_ratio",
        "agent_cash_gap_rate",
    }
)

# Known forbidden columns across protected categories, ground truth labels,
# sidecar observations, and system identifiers.
FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        # Protected demographic and evaluation slices (Fairness only)
        "gender",
        "age_band",
        "region",
        "urban_rural",
        # Generator ground-truth labels
        "group_label",
        "agent_type",
        "behavior_profile",
        # Simulation observation sidecar ground truth / leakage
        "actual_cash_received",
        "actual_cash",
        "cash_received_reported",
        "reported_cash",
        "payout_reduction",
        "fee_overcharge",
        "is_skimmer_action",
        "behavior_flipped",
        "is_loyal",
        "reduction_amount",
        "sampled_top_agent_share",
        "agent_assisted_customer_ratio",
        # System entity identifiers
        "user_id",
        "agent_id",
        "txn_id",
        "session_id",
        "mandate_id",
        "case_id",
        "score_id",
        "log_id",
        "event_id",
        "action_id",
        "code_hash",
    }
)


def assert_feature_columns(columns: Iterable[str] | Any) -> None:
    """Assert feature columns contain only approved numeric behavioral features.

    Rejects:
    - Protected demographic / fairness slices (gender, age_band, region, urban_rural)
    - Generator ground truth labels (group_label, agent_type, behavior_profile)
    - Simulation truth and raw cash observations.
    - Identifiers (user_id, agent_id, txn_id, session_id, etc.)
    - Unknown or accidental future columns via strict allowlist enforcement.
    - Empty column collections.
    """
    if hasattr(columns, "columns"):
        # Support pandas DataFrame / Series if passed
        cols = list(columns.columns)
    elif isinstance(columns, (list, tuple, set, frozenset)):
        cols = list(columns)
    elif isinstance(columns, Iterable) and not isinstance(columns, (str, bytes)):
        cols = list(columns)
    else:
        raise FeatureLeakageError(
            f"Columns must be an iterable collection of strings, got {type(columns).__name__}"
        )

    if not cols:
        raise FeatureLeakageError("Feature column collection cannot be empty.")

    # 1. Reject known forbidden columns with clear, explicit category diagnosis
    for col in cols:
        if not isinstance(col, str):
            raise FeatureLeakageError(
                f"Feature column name must be string, got {type(col).__name__}"
            )
        if col in FORBIDDEN_COLUMNS:
            raise FeatureLeakageError(
                f"Feature leakage error: forbidden column '{col}' detected. "
                "Protected attributes, ground-truth labels, and identifiers are "
                "strictly prohibited in feature representations."
            )

    # 2. Enforce strict allowlist to prevent accidental future columns
    unknown = set(cols) - ALLOWED_NUMERIC_BEHAVIORAL_FEATURES
    if unknown:
        raise FeatureLeakageError(
            f"Unauthorized feature column(s) detected: {sorted(unknown)}. "
            "Only explicit allowlist numeric behavioral features are permitted."
        )
