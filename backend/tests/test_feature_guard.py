"""Unit tests for feature leakage guard and column allowlist enforcement."""

import pytest
from app.features.guard import (
    ALLOWED_NUMERIC_BEHAVIORAL_FEATURES,
    FORBIDDEN_COLUMNS,
    FeatureLeakageError,
    assert_feature_columns,
)


def test_positive_allowlist_features_pass():
    """Verify that approved numeric behavioral features pass validation without error."""
    # Subset of allowlist features
    sample_allowed = [
        "top_agent_share",
        "cash_out_tx_count",
        "credit_to_cashout_hours_mean",
        "withdrawn_balance_ratio_mean",
        "pin_retries_mean",
        "pin_entry_seconds_median",
        "session_steps_mean",
        "agent_assisted_tx_ratio",
    ]
    assert_feature_columns(sample_allowed)

    # Full set of allowlist features
    assert_feature_columns(list(ALLOWED_NUMERIC_BEHAVIORAL_FEATURES))


def test_positive_single_allowed_feature_passes():
    """Verify single allowed feature passes."""
    assert_feature_columns(["top_agent_share"])
    assert_feature_columns(["cash_out_total_amount"])


def test_empty_columns_rejected():
    """Reject empty feature column collections."""
    with pytest.raises(FeatureLeakageError, match="cannot be empty"):
        assert_feature_columns([])
    with pytest.raises(FeatureLeakageError, match="cannot be empty"):
        assert_feature_columns(set())


@pytest.mark.parametrize("forbidden_col", sorted(FORBIDDEN_COLUMNS))
def test_parametric_every_forbidden_column_rejected(forbidden_col):
    """Parametrically verify that EVERY single forbidden column is rejected."""
    # Solo forbidden column
    with pytest.raises(FeatureLeakageError, match="forbidden column"):
        assert_feature_columns([forbidden_col])

    # Forbidden column bundled with valid allowed features
    mixed = ["top_agent_share", forbidden_col, "cash_out_tx_count"]
    with pytest.raises(FeatureLeakageError, match="forbidden column"):
        assert_feature_columns(mixed)


@pytest.mark.parametrize(
    "unknown_col",
    [
        "accidental_future_feature",
        "raw_text_note",
        "unauthorized_score",
        "user_balance_delta_ratio_custom",
        "foo_bar",
    ],
)
def test_unknown_future_columns_rejected_via_allowlist(unknown_col):
    """Ensure column not in approved allowlist is rejected, preventing future leakage."""
    with pytest.raises(FeatureLeakageError, match="Unauthorized feature column"):
        assert_feature_columns([unknown_col])

    with pytest.raises(FeatureLeakageError, match="Unauthorized feature column"):
        assert_feature_columns(["top_agent_share", unknown_col])


def test_invalid_column_types_rejected():
    """Reject non-string column elements."""
    with pytest.raises(FeatureLeakageError, match="must be string"):
        assert_feature_columns([123, "top_agent_share"])

    with pytest.raises(FeatureLeakageError, match="must be an iterable"):
        assert_feature_columns(None)


def test_dataframe_like_columns_attribute_supported():
    """Verify objects with a .columns attribute (e.g. pandas DataFrame) are inspected correctly."""

    class MockDataFrame:
        def __init__(self, cols):
            self.columns = cols

    # Valid mock dataframe
    valid_df = MockDataFrame(["top_agent_share", "pin_retries_mean"])
    assert_feature_columns(valid_df)

    # Invalid mock dataframe with protected attribute
    leaky_df = MockDataFrame(["top_agent_share", "gender"])
    with pytest.raises(FeatureLeakageError, match="forbidden column"):
        assert_feature_columns(leaky_df)


def test_latent_metadata_and_ground_truth_ratio_strictly_forbidden():
    """Verify sampled_top_agent_share and agent_assisted_customer_ratio are rejected."""
    with pytest.raises(FeatureLeakageError, match="forbidden column"):
        assert_feature_columns(["sampled_top_agent_share"])

    with pytest.raises(FeatureLeakageError, match="forbidden column"):
        assert_feature_columns(["agent_assisted_customer_ratio"])

    # Observed aggregate top_agent_share is permitted
    assert_feature_columns(["top_agent_share"])
