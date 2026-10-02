"""Unit and statistical tests for synthetic generator, observations sidecar, and determinism."""

import copy
import hashlib
import json
import random
from datetime import datetime
from decimal import Decimal

import pytest
from app.data.config import ConfigError, find_config_path, load_config
from app.data.database import compute_dataset_checksum, validate_dataset
from app.data.generator import (
    generate_dataset,
    generate_dataset_with_observations,
)


@pytest.fixture
def base_config():
    """Return loaded base configuration copy."""
    return load_config()


def test_determinism_identical_canonical_bytes(base_config):
    """Verify same seed and config produce 100% identical canonical bytes and hashes."""
    res1, obs1 = generate_dataset_with_observations(base_config, seed=42, customers=100)
    res2, obs2 = generate_dataset_with_observations(base_config, seed=42, customers=100)

    b1_main = json.dumps(res1, sort_keys=True, separators=(",", ":")).encode("utf-8")
    b2_main = json.dumps(res2, sort_keys=True, separators=(",", ":")).encode("utf-8")

    b1_obs = json.dumps(obs1, sort_keys=True, separators=(",", ":")).encode("utf-8")
    b2_obs = json.dumps(obs2, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert b1_main == b2_main, "Main dataset canonical bytes must be identical"
    assert b1_obs == b2_obs, "Sidecar canonical bytes must be identical"
    assert hashlib.sha256(b1_main).hexdigest() == hashlib.sha256(b2_main).hexdigest()


def test_different_seeds_differ(base_config):
    """Verify different seeds produce distinct outputs, user IDs, and checksums."""
    res1 = generate_dataset(base_config, seed=42, customers=80)
    res2 = generate_dataset(base_config, seed=4242, customers=80)

    assert compute_dataset_checksum(res1) != compute_dataset_checksum(res2)
    assert res1["users"][0]["user_id"].startswith("U_42_")
    assert res2["users"][0]["user_id"].startswith("U_4242_")


def test_global_random_untouched(base_config):
    """Verify generator uses isolated RNG and leaves global random state untouched."""
    random.seed(123456789)
    state_before = random.getstate()

    generate_dataset(base_config, seed=42, customers=50)

    state_after = random.getstate()
    assert state_before == state_after, "Global random state must not be modified"


def test_canonical_agent_registry_stable_across_seeds(base_config):
    """Verify agent registry is generated with seed_train RNG so agents are stable."""
    res_seed42 = generate_dataset(base_config, seed=42, customers=50)
    res_seed2026 = generate_dataset(base_config, seed=2026, customers=50)

    # Agents must be completely identical across generation seeds
    assert res_seed42["agents"] == res_seed2026["agents"]
    assert len(res_seed42["agents"]) == base_config["simulation"]["agents"]
    assert res_seed42["agents"][0]["agent_id"] == "A_000000"


def test_users_and_agents_counts_and_cohort_filtering(base_config):
    """Verify custom customer counts and strict agent cohort isolation for T015."""
    target_customers = 75
    res = generate_dataset(base_config, seed=42, customers=target_customers)
    assert len(res["users"]) == target_customers

    # Test explicit agent cohort routing
    explicit_cohort = ["A_000001", "A_000010", "A_000050"]
    cohort_res = generate_dataset(
        base_config,
        seed=42,
        customers=50,
        agent_ids=explicit_cohort,
    )
    assert len(cohort_res["agents"]) == len(explicit_cohort)
    assert {a["agent_id"] for a in cohort_res["agents"]} == set(explicit_cohort)

    # All transactions must strictly route within the explicit cohort
    for t in cohort_res["transactions"]:
        if t["agent_id"] is not None:
            assert t["agent_id"] in explicit_cohort, (
                f"Txn {t['txn_id']} routed outside cohort: {t['agent_id']}"
            )


def test_foreign_keys_and_session_joins(base_config):
    """Verify relational integrity: foreign keys and session consistency."""
    res, _ = generate_dataset_with_observations(base_config, seed=42, customers=100)

    user_ids = {u["user_id"] for u in res["users"]}
    agent_ids = {a["agent_id"] for a in res["agents"]}
    txn_user_map = {t["txn_id"]: t["user_id"] for t in res["transactions"]}

    for t in res["transactions"]:
        assert t["user_id"] in user_ids
        if t["agent_id"] is not None:
            assert t["agent_id"] in agent_ids

    for s in res["sessions"]:
        assert s["user_id"] in user_ids
        tid = s.get("txn_id")
        if tid is not None:
            assert tid in txn_user_map
            assert txn_user_map[tid] == s["user_id"], "Session and txn user_id must match"


def test_chronological_per_user_credit_debit_balance(base_config):
    """Verify chronological ordering, strict balance constraints, and 2-decimal money."""
    res = generate_dataset(base_config, seed=42, customers=120)

    txns_by_user: dict[str, list[dict]] = {}
    for t in res["transactions"]:
        txns_by_user.setdefault(t["user_id"], []).append(t)

    for uid, u_txns in txns_by_user.items():
        # Check non-decreasing timestamps
        for i in range(len(u_txns) - 1):
            assert u_txns[i]["ts"] <= u_txns[i + 1]["ts"], f"User {uid} txn not chronological"

        running_balance = Decimal("0.00")
        for t in u_txns:
            amt = Decimal(str(t["amount"]))
            fee = Decimal(str(t.get("fee", 0.0)))
            bal_after = Decimal(str(t["balance_after"]))

            # Verify strictly 2 decimal places
            assert amt == amt.quantize(Decimal("0.01")), f"Amount {amt} not 2 decimals"
            assert fee == fee.quantize(Decimal("0.01")), f"Fee {fee} not 2 decimals"
            assert bal_after == bal_after.quantize(Decimal("0.01")), "Balance not 2 decimals"

            if t["txn_type"] == "credit":
                running_balance += amt
            elif t["txn_type"] in ("cash_out", "send", "bill_pay"):
                assert amt + fee <= running_balance, (
                    f"Debit {amt} + fee {fee} exceeds balance {running_balance}"
                )
                running_balance -= amt + fee

            assert running_balance >= Decimal("0.00"), f"User {uid} balance negative"
            assert running_balance == bal_after, (
                f"Ledger discrepancy for user {uid}: expected {running_balance}, got {bal_after}"
            )


def test_customer_report_rate_and_noise_statistical_checks(base_config):
    """Verify customer reporting rate and noise characteristics across cash-outs."""
    _, obs = generate_dataset_with_observations(base_config, seed=42, customers=400)
    tx_obs = obs["transaction_observations"]

    cashout_records = [
        rec for rec in tx_obs.values() if rec.get("actual_cash_received") is not None
    ]
    assert len(cashout_records) > 50

    reported = [r for r in cashout_records if r["cash_received_reported"] is not None]
    report_rate = len(reported) / len(cashout_records)
    assert 0.45 <= report_rate <= 0.75, f"Report rate {report_rate} outside [0.45, 0.75]"

    accurate_count = sum(
        1 for r in reported if r["cash_received_reported"] == r["actual_cash_received"]
    )
    accuracy_rate = accurate_count / len(reported)
    assert 0.75 <= accuracy_rate <= 0.98, f"Report accuracy {accuracy_rate} outside range"


def test_customer_report_rate_and_accuracy_extremes_0_and_1(base_config):
    """Verify customer reporting rate and accuracy respond to 0.0 and 1.0 extremes."""
    # Rate = 0.0: all reports must be None
    cfg_zero_rate = copy.deepcopy(base_config)
    cfg_zero_rate["simulation"]["customer_report_rate"] = 0.0
    _, obs_zero = generate_dataset_with_observations(cfg_zero_rate, seed=42, customers=100)
    for rec in obs_zero["transaction_observations"].values():
        assert rec["cash_received_reported"] is None

    # Rate = 1.0 and Accuracy = 1.0: all reports must equal actual cash
    cfg_perfect = copy.deepcopy(base_config)
    cfg_perfect["simulation"]["customer_report_rate"] = 1.0
    cfg_perfect["simulation"]["customer_report_accuracy"] = 1.0
    _, obs_perf = generate_dataset_with_observations(cfg_perfect, seed=42, customers=100)
    for rec in obs_perf["transaction_observations"].values():
        assert rec["cash_received_reported"] == rec["actual_cash_received"]

    # Rate = 1.0 and Accuracy = 0.0: noise applied to all reports
    cfg_noisy = copy.deepcopy(base_config)
    cfg_noisy["simulation"]["customer_report_rate"] = 1.0
    cfg_noisy["simulation"]["customer_report_accuracy"] = 0.0
    _, obs_noisy = generate_dataset_with_observations(cfg_noisy, seed=42, customers=100)
    recs = list(obs_noisy["transaction_observations"].values())
    assert len(recs) > 0
    differ_count = sum(1 for r in recs if r["cash_received_reported"] != r["actual_cash_received"])
    assert differ_count > 0


def test_high_volume_honest_no_overfee(base_config):
    """Verify that high-volume honest agents NEVER charge more than official fee."""
    res, obs = generate_dataset_with_observations(base_config, seed=42, customers=200)
    tx_obs = obs["transaction_observations"]

    honest_high_vol_cashouts = [
        r for r in tx_obs.values() if r.get("agent_type") == "high_volume_honest"
    ]
    assert len(honest_high_vol_cashouts) > 0

    for r in honest_high_vol_cashouts:
        assert r["fee_overcharge"] == 0.0, "High-volume honest must never overcharge fee"
        assert r["payout_reduction"] == 0.0, "High-volume honest must never reduce payout"
        assert not r["is_skimmer_action"]


def test_agent_skimming_extremes_0_and_1_not_flaky(base_config):
    """Verify skimming behavior deterministically responds to 0% and 100% overrides."""
    # 1. Extreme 100%: All skimmer cashouts must overcharge and reduce payout
    cfg_100 = copy.deepcopy(base_config)
    skimmer_mod = cfg_100["simulation"]["agent_behavior"]["skimmers"]["intensity_profiles"][
        "moderate"
    ]
    skimmer_mod["fee_multiplier_probability"] = 1.0
    skimmer_mod["payout_reduction_probability"] = 1.0

    _, obs_100 = generate_dataset_with_observations(cfg_100, seed=42, customers=150)
    skimmer_obs_100 = [
        r for r in obs_100["transaction_observations"].values() if r.get("agent_type") == "skimmer"
    ]
    assert len(skimmer_obs_100) > 0
    for r in skimmer_obs_100:
        assert r["fee_overcharge"] > 0.0, "At prob=1.0, fee overcharge must occur"
        assert r["payout_reduction"] > 0.0, "At prob=1.0, payout reduction must occur"
        assert r["is_skimmer_action"] is True

    # 2. Extreme 0%: Zero skimmer cashouts overcharge or reduce payout
    cfg_0 = copy.deepcopy(base_config)
    skimmer_mod_0 = cfg_0["simulation"]["agent_behavior"]["skimmers"]["intensity_profiles"][
        "moderate"
    ]
    skimmer_mod_0["fee_multiplier_probability"] = 0.0
    skimmer_mod_0["payout_reduction_probability"] = 0.0

    _, obs_0 = generate_dataset_with_observations(cfg_0, seed=42, customers=150)
    skimmer_obs_0 = [
        r for r in obs_0["transaction_observations"].values() if r.get("agent_type") == "skimmer"
    ]
    assert len(skimmer_obs_0) > 0
    for r in skimmer_obs_0:
        assert r["fee_overcharge"] == 0.0, "At prob=0.0, fee overcharge must be zero"
        assert r["payout_reduction"] == 0.0, "At prob=0.0, payout reduction must be zero"
        assert r["is_skimmer_action"] is False


@pytest.mark.parametrize("intensity", ["subtle", "moderate", "obvious"])
def test_all_three_skimming_intensity_paths(base_config, intensity):
    """Verify all three skimming intensity profiles execute accurately."""
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["skimming_intensity"] = intensity
    profile = cfg["simulation"]["agent_behavior"]["skimmers"]["intensity_profiles"][intensity]
    profile["fee_multiplier_probability"] = 1.0
    profile["payout_reduction_probability"] = 1.0

    _, obs = generate_dataset_with_observations(cfg, seed=42, customers=100)
    skimmer_actions = [
        r for r in obs["transaction_observations"].values() if r.get("agent_type") == "skimmer"
    ]
    assert len(skimmer_actions) > 0

    low_pct, high_pct = profile["payout_reduction_range"]

    for r in skimmer_actions:
        assert r["is_skimmer_action"] is True
        amt = r["actual_cash_received"] + r["payout_reduction"]
        actual_pct = r["payout_reduction"] / amt
        assert (low_pct - 0.005) <= actual_pct <= (high_pct + 0.005), (
            f"Reduction {actual_pct} outside profile range [{low_pct}, {high_pct}]"
        )


def test_invalid_nested_config_incl_nan_and_bools(base_config):
    """Verify config validator rejects invalid nested parameters, NaNs, and bools."""
    # Test bool rejected in numeric fields
    for field_path in [
        ("simulation", "customers"),
        ("simulation", "agents"),
        ("simulation", "days"),
        ("simulation", "seed_train"),
        ("simulation", "allowance_day_of_cycle"),
        ("simulation", "official_fee_rate"),
    ]:
        cfg = copy.deepcopy(base_config)
        cfg[field_path[0]][field_path[1]] = True
        with pytest.raises(ConfigError):
            generate_dataset(cfg)

    # Test NaN and inf rejected
    cfg_nan = copy.deepcopy(base_config)
    cfg_nan["simulation"]["official_fee_rate"] = float("nan")
    with pytest.raises(ConfigError):
        generate_dataset(cfg_nan)

    cfg_inf = copy.deepcopy(base_config)
    cfg_inf["simulation"]["distributions"]["credit_to_cashout_delay_hours"]["assisted"]["mean"] = (
        float("inf")
    )
    with pytest.raises(ConfigError):
        generate_dataset(cfg_inf)

    # Test beta alpha/beta <= 0
    cfg_beta = copy.deepcopy(base_config)
    cfg_beta["simulation"]["distributions"]["top_agent_share"]["assisted"]["alpha"] = 0.0
    with pytest.raises(ConfigError):
        generate_dataset(cfg_beta)

    # Test exponential mean <= 0
    cfg_exp = copy.deepcopy(base_config)
    cfg_exp["simulation"]["distributions"]["credit_to_cashout_delay_hours"]["assisted"]["mean"] = (
        0.0
    )
    with pytest.raises(ConfigError):
        generate_dataset(cfg_exp)

    # Test lognormal median <= 0 and sigma < 0
    cfg_ln = copy.deepcopy(base_config)
    cfg_ln["simulation"]["distributions"]["pin_entry_seconds"]["assisted"]["median"] = -1.0
    with pytest.raises(ConfigError):
        generate_dataset(cfg_ln)

    cfg_ln2 = copy.deepcopy(base_config)
    cfg_ln2["simulation"]["distributions"]["pin_entry_seconds"]["assisted"]["sigma"] = -0.5
    with pytest.raises(ConfigError):
        generate_dataset(cfg_ln2)

    # Test poisson lambda < 0
    cfg_poi = copy.deepcopy(base_config)
    cfg_poi["simulation"]["distributions"]["pin_retries"]["assisted"]["lambda"] = -0.1
    with pytest.raises(ConfigError):
        generate_dataset(cfg_poi)

    # Test invalid distribution name
    cfg_dist = copy.deepcopy(base_config)
    cfg_dist["simulation"]["distributions"]["top_agent_share"]["assisted"]["dist"] = "gamma"
    with pytest.raises(ConfigError):
        generate_dataset(cfg_dist)

    # Test credit cycle_days <= 0 and min > max
    cfg_cyc = copy.deepcopy(base_config)
    cfg_cyc["simulation"]["credits"]["allowance"]["cycle_days"] = 0
    with pytest.raises(ConfigError):
        generate_dataset(cfg_cyc)

    cfg_cmin = copy.deepcopy(base_config)
    cfg_cmin["simulation"]["credits"]["allowance"]["amount_min"] = 6000
    cfg_cmin["simulation"]["credits"]["allowance"]["amount_max"] = 5000
    with pytest.raises(ConfigError):
        generate_dataset(cfg_cmin)

    # Test duplicate credits.allowance.disbursement_day rejected
    cfg_dup = copy.deepcopy(base_config)
    cfg_dup["simulation"]["credits"]["allowance"]["disbursement_day"] = 5
    with pytest.raises(ConfigError):
        generate_dataset(cfg_dup)

    # Test duplicate seeds rejected
    cfg_seeds = copy.deepcopy(base_config)
    cfg_seeds["simulation"]["seed_validation"] = cfg_seeds["simulation"]["seed_train"]
    with pytest.raises(ConfigError):
        generate_dataset(cfg_seeds)

    # Test agent_split not summing to 1.0
    cfg_split = copy.deepcopy(base_config)
    cfg_split["simulation"]["agent_split"]["train"] = 0.8
    with pytest.raises(ConfigError):
        generate_dataset(cfg_split)


def test_generator_argument_validation(base_config):
    """Verify generate_dataset rejects invalid seed, customer counts, and unknown agent IDs."""
    # Bool seed
    with pytest.raises(ConfigError):
        generate_dataset(base_config, seed=True)

    # Negative seed
    with pytest.raises(ConfigError):
        generate_dataset(base_config, seed=-5)

    # Non-31-bit seed
    with pytest.raises(ConfigError):
        generate_dataset(base_config, seed=2**31)

    # Bool customers
    with pytest.raises(ConfigError):
        generate_dataset(base_config, customers=True)

    # Non-positive customers
    with pytest.raises(ConfigError):
        generate_dataset(base_config, customers=0)

    # Unknown agent IDs must be rejected, not silently ignored
    with pytest.raises(ConfigError, match="unknown agent IDs"):
        generate_dataset(base_config, agent_ids=["A_999999"])

    with pytest.raises(ConfigError, match="unknown agent IDs"):
        generate_dataset(base_config, agent_ids=["A_000001", "NON_EXISTENT"])

    # Empty agent IDs
    with pytest.raises(ConfigError, match="cannot be empty"):
        generate_dataset(base_config, agent_ids=[])


def test_label_noise_0_and_1_behavior_stable_ground_truth(base_config):
    """Verify label noise flips effective profile while retaining ground truth label."""
    # 0% noise
    cfg0 = copy.deepcopy(base_config)
    cfg0["simulation"]["label_noise"] = 0.0
    res0, obs0 = generate_dataset_with_observations(cfg0, seed=42, customers=100)
    for u in res0["users"]:
        uid = u["user_id"]
        assert obs0["user_observations"][uid]["behavior_flipped"] is False
        assert obs0["user_observations"][uid]["effective_profile"] == u["group_label"]

    # 100% noise
    cfg1 = copy.deepcopy(base_config)
    cfg1["simulation"]["label_noise"] = 1.0
    res1, obs1 = generate_dataset_with_observations(cfg1, seed=42, customers=100)
    for u in res1["users"]:
        uid = u["user_id"]
        assert obs1["user_observations"][uid]["behavior_flipped"] is True
        # Ground truth label must still match group label quota
        assert u["group_label"] in base_config["simulation"]["group_shares"]


def test_loyalty_and_overlap_evidence(base_config):
    """Verify loyal independent users adopt assisted Beta(6, 2) top-agent share."""
    _, obs = generate_dataset_with_observations(base_config, seed=42, customers=500)
    user_obs = obs["user_observations"]

    indep_users = [u for u in user_obs.values() if not u["is_assisted_behavior"]]
    loyal_users = [u for u in indep_users if u["is_loyal"]]
    non_loyal_users = [u for u in indep_users if not u["is_loyal"]]

    assert len(loyal_users) > 0
    assert len(non_loyal_users) > 0

    loyal_ratio = len(loyal_users) / len(indep_users)
    assert 0.08 <= loyal_ratio <= 0.25

    avg_loyal_top_share = sum(u["sampled_top_agent_share"] for u in loyal_users) / len(loyal_users)
    avg_non_loyal_top_share = sum(u["sampled_top_agent_share"] for u in non_loyal_users) / len(
        non_loyal_users
    )

    # Beta(6, 2) has mean 0.75, whereas Beta(2, 5) is 0.28 and Beta(3, 4) is 0.43
    assert avg_loyal_top_share > avg_non_loyal_top_share


def test_config_parameter_edits_affect_output(base_config):
    """Verify modifying configuration parameters alters dataset checksum."""
    res_base = generate_dataset(base_config, seed=42, customers=80)
    cs_base = compute_dataset_checksum(res_base)

    cfg_mod = copy.deepcopy(base_config)
    cfg_mod["simulation"]["auxiliary_assumptions"]["initial_balance"] = 3000
    res_mod = generate_dataset(cfg_mod, seed=42, customers=80)
    cs_mod = compute_dataset_checksum(res_mod)

    assert cs_base != cs_mod, "Changing initial_balance must affect dataset output"


def test_validate_generated_main_via_loader(base_config):
    """Verify that generated main dataset satisfies pure validate_dataset checks."""
    res = generate_dataset(base_config, seed=42, customers=100)
    validate_dataset(res)
    assert compute_dataset_checksum(res) is not None


def test_opening_balance_credit_source_is_add_money(base_config):
    """Verify initial balance top-up is always add_money, even for allowance users."""
    res = generate_dataset(base_config, seed=42, customers=60)
    for u in res["users"]:
        uid = u["user_id"]
        u_credits = [
            t for t in res["transactions"] if t["user_id"] == uid and t["txn_type"] == "credit"
        ]
        assert len(u_credits) > 0
        first_credit = u_credits[0]
        assert first_credit["credit_source"] == "add_money", (
            f"User {uid} first credit has {first_credit['credit_source']}, expected add_money"
        )


def test_metadata_sampled_top_agent_share_renamed(base_config):
    """Verify sidecar metadata uses sampled_top_agent_share, not top_agent_share."""
    _, obs = generate_dataset_with_observations(base_config, seed=42, customers=50)
    for meta in obs["user_observations"].values():
        assert "sampled_top_agent_share" in meta
        assert "top_agent_share" not in meta
        assert 0.0 <= meta["sampled_top_agent_share"] <= 1.0


def test_high_volume_allowance_multiplier_1_vs_2_controlled_fixture(base_config):
    """Verify allowance_day_volume_multiplier 1 vs 2 changes emitted amounts on allowance day."""
    cfg1 = copy.deepcopy(base_config)
    cfg1["simulation"]["agent_behavior"]["high_volume_honest"][
        "allowance_day_volume_multiplier"
    ] = 1.0
    res1 = generate_dataset(cfg1, seed=42, customers=150)

    cfg2 = copy.deepcopy(base_config)
    cfg2["simulation"]["agent_behavior"]["high_volume_honest"][
        "allowance_day_volume_multiplier"
    ] = 2.0
    res2 = generate_dataset(cfg2, seed=42, customers=150)

    cs1 = compute_dataset_checksum(res1)
    cs2 = compute_dataset_checksum(res2)
    assert cs1 != cs2, "Multiplier 1.0 vs 2.0 must produce different transactions"

    start_dt = datetime.fromisoformat(cfg1["simulation"]["start_timestamp"].replace("Z", "+00:00"))
    allow_cycle_days = cfg1["simulation"]["credits"]["allowance"]["cycle_days"]
    allow_day = cfg1["simulation"]["allowance_day_of_cycle"]

    def is_allow_day(ts_str):
        dt = datetime.fromisoformat(ts_str)
        return ((dt - start_dt).days % allow_cycle_days) == allow_day

    # Verify each cashout has exactly one session and no duplicate split timestamps
    hv_agent_ids = {
        a["agent_id"] for a in res1["agents"] if a["agent_type"] == "high_volume_honest"
    }
    for res in (res1, res2):
        txns = res["transactions"]
        sessions = res["sessions"]
        co_txns = [t for t in txns if t["txn_type"] == "cash_out" and t["agent_id"] in hv_agent_ids]
        assert len(co_txns) > 0
        txn_ids = {t["txn_id"] for t in co_txns}
        sess_txns = [s["txn_id"] for s in sessions if s.get("txn_id") in txn_ids]
        assert len(sess_txns) == len(co_txns)

    hv_allow_txns_1 = [
        t
        for t in res1["transactions"]
        if t["txn_type"] == "cash_out" and t["agent_id"] in hv_agent_ids and is_allow_day(t["ts"])
    ]
    hv_allow_txns_2 = [
        t
        for t in res2["transactions"]
        if t["txn_type"] == "cash_out" and t["agent_id"] in hv_agent_ids and is_allow_day(t["ts"])
    ]
    if hv_allow_txns_1 and hv_allow_txns_2:
        total_amt_1 = sum(t["amount"] for t in hv_allow_txns_1)
        total_amt_2 = sum(t["amount"] for t in hv_allow_txns_2)
        assert total_amt_2 > total_amt_1, "Multiplier 2.0 must emit higher cashout volume than 1.0"


def test_service_count_lambda_0_vs_larger(base_config):
    """Verify total_services actual draw drives extra-service intents per cycle."""
    cfg0 = copy.deepcopy(base_config)
    cfg0["simulation"]["distributions"]["service_count"]["independent"]["base"] = 1
    cfg0["simulation"]["distributions"]["service_count"]["independent"]["lambda"] = 0.0
    cfg0["simulation"]["distributions"]["service_count"]["assisted"]["base"] = 1
    cfg0["simulation"]["distributions"]["service_count"]["assisted"]["lambda"] = 0.0
    cfg0["simulation"]["auxiliary_assumptions"]["extra_service"]["probability_per_cycle"] = 1.0
    res0 = generate_dataset(cfg0, seed=42, customers=50)

    cfg8 = copy.deepcopy(base_config)
    cfg8["simulation"]["distributions"]["service_count"]["independent"]["base"] = 1
    cfg8["simulation"]["distributions"]["service_count"]["independent"]["lambda"] = 8.0
    cfg8["simulation"]["distributions"]["service_count"]["assisted"]["base"] = 1
    cfg8["simulation"]["distributions"]["service_count"]["assisted"]["lambda"] = 8.0
    cfg8["simulation"]["auxiliary_assumptions"]["extra_service"]["probability_per_cycle"] = 1.0
    res8 = generate_dataset(cfg8, seed=42, customers=50)

    extra_txns_0 = [t for t in res0["transactions"] if t["txn_type"] in ("send", "bill_pay")]
    extra_txns_8 = [t for t in res8["transactions"] if t["txn_type"] in ("send", "bill_pay")]

    assert len(extra_txns_8) > len(extra_txns_0) * 2


def test_varied_cycles_and_rounding_amount(base_config):
    """Verify generator correctly handles varied cycle_days and amount_rounding_bdt."""
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["credits"]["allowance"]["cycle_days"] = 15
    cfg["simulation"]["credits"]["independent"]["cycle_days"] = 15
    cfg["simulation"]["auxiliary_assumptions"]["amount_rounding_bdt"] = 100
    res = generate_dataset(cfg, seed=42, customers=60)

    for t in res["transactions"]:
        amt = Decimal(str(t["amount"]))
        assert amt > Decimal("0.00")
        assert amt == amt.quantize(Decimal("0.01"))


def test_legacy_config_env(tmp_path, monkeypatch):
    dummy_config = tmp_path / "dummy_config.yaml"
    dummy_config.write_text("simulation: {}", encoding="utf-8")
    monkeypatch.setenv("SATHI_CONFIG", str(dummy_config))
    assert find_config_path() == dummy_config
    monkeypatch.delenv("SATHI_CONFIG")
    monkeypatch.setenv("SATHI_CONFIG_PATH", str(dummy_config))
    assert find_config_path() == dummy_config


def test_short_cycle_and_small_population(base_config):
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["days"] = 3
    cfg["simulation"]["allowance_day_of_cycle"] = 0
    cfg["simulation"]["credits"]["allowance"]["cycle_days"] = 1
    cfg["simulation"]["credits"]["independent"]["cycle_days"] = 1
    cfg["simulation"]["auxiliary_assumptions"]["extra_service"]["probability_per_cycle"] = 1
    data = generate_dataset(cfg, customers=3)
    assert len(data["users"]) == 3
    validate_dataset(data)
