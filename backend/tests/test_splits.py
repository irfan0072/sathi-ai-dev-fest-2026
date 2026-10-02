"""Tests for disjoint agent and seed split tooling (T015)."""

import copy
import hashlib
import json

import pytest
import yaml
from app.data.cli import main as cli_main
from app.data.config import ConfigError, load_config
from app.data.database import compute_dataset_checksum, validate_dataset
from app.data.generator import build_canonical_agent_registry
from app.data.splits import (
    allocate_cohorts,
    allocate_largest_remainder,
    assert_disjoint_splits,
    generate_splits,
    write_splits,
)


@pytest.fixture(scope="module")
def base_config():
    """Return loaded default simulation configuration."""
    return load_config()


@pytest.fixture(scope="module")
def small_config(base_config):
    """Return small configuration fixture (60 customers, 30 agents) for fast testing."""
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["customers"] = 60
    cfg["simulation"]["agents"] = 30
    cfg["simulation"]["agent_mix"] = {
        "normal": 20,
        "high_volume_honest": 6,
        "skimmers": 4,
    }
    return cfg


@pytest.fixture(scope="module")
def small_splits(small_config):
    """Generate small splits once for contamination, repeat, and export tests."""
    return generate_splits(small_config)


@pytest.fixture(scope="module")
def full_splits(base_config):
    """Generate full default splits once for the test module."""
    return generate_splits(base_config)


def test_allocate_largest_remainder():
    """Verify largest-remainder allocation preserves exact totals and handles fractional shares."""
    ratios = {"train": 0.60, "validation": 0.20, "test": 0.20}

    # Customers: 20000 -> 12000 / 4000 / 4000
    c_alloc = allocate_largest_remainder(20000, ratios)
    assert c_alloc == {"train": 12000, "validation": 4000, "test": 4000}
    assert sum(c_alloc.values()) == 20000

    # Agents: 300 -> 180 / 60 / 60
    a_alloc = allocate_largest_remainder(300, ratios)
    assert a_alloc == {"train": 180, "validation": 60, "test": 60}
    assert sum(a_alloc.values()) == 300

    # Subtypes: normal 270 -> 162 / 54 / 54
    assert allocate_largest_remainder(270, ratios) == {
        "train": 162,
        "validation": 54,
        "test": 54,
    }

    # high_volume_honest 20 -> 12 / 4 / 4
    assert allocate_largest_remainder(20, ratios) == {
        "train": 12,
        "validation": 4,
        "test": 4,
    }

    # skimmers 10 -> 6 / 2 / 2
    assert allocate_largest_remainder(10, ratios) == {
        "train": 6,
        "validation": 2,
        "test": 2,
    }

    # Fractional remainder tie-break check (total=10, 3 equal ratios 1/3)
    three_way = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    t_alloc = allocate_largest_remainder(10, three_way)
    assert sum(t_alloc.values()) == 10
    assert t_alloc == {"a": 4, "b": 3, "c": 3}


def test_allocate_cohorts_stratification_default(base_config):
    """Verify default 300 agents allocate into exact 180/60/60 cohorts stratified by type."""
    cohorts = allocate_cohorts(base_config)
    assert set(cohorts.keys()) == {"train", "validation", "test"}

    assert len(cohorts["train"]) == 180
    assert len(cohorts["validation"]) == 60
    assert len(cohorts["test"]) == 60

    # All cohorts must be mutually disjoint
    train_set = set(cohorts["train"])
    val_set = set(cohorts["validation"])
    test_set = set(cohorts["test"])

    assert train_set & val_set == set()
    assert train_set & test_set == set()
    assert val_set & test_set == set()
    assert len(train_set | val_set | test_set) == 300

    # Check stratification counts per agent type
    canonical_agents = build_canonical_agent_registry(base_config)
    agent_type_map = {a["agent_id"]: a["agent_type"] for a in canonical_agents}

    for c_name, expected_counts in (
        ("train", {"normal": 162, "high_volume_honest": 12, "skimmer": 6}),
        ("validation", {"normal": 54, "high_volume_honest": 4, "skimmer": 2}),
        ("test", {"normal": 54, "high_volume_honest": 4, "skimmer": 2}),
    ):
        actual_counts = {"normal": 0, "high_volume_honest": 0, "skimmer": 0}
        for aid in cohorts[c_name]:
            actual_counts[agent_type_map[aid]] += 1
        assert actual_counts == expected_counts, f"Mismatch in {c_name} stratification"


def test_allocate_cohorts_deterministic(base_config):
    """Verify allocate_cohorts produces identical allocations across calls."""
    c1 = allocate_cohorts(base_config)
    c2 = allocate_cohorts(base_config)
    assert c1 == c2


def test_allocate_cohorts_uneven_nine_agents(base_config):
    """Verify 9 agents with mix 3/3/3 reconcile to 5/2/2 global quotas without empty cohorts."""
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["agents"] = 9
    cfg["simulation"]["agent_mix"] = {
        "normal": 3,
        "high_volume_honest": 3,
        "skimmers": 3,
    }
    cfg["simulation"]["customers"] = 30

    cohorts = allocate_cohorts(cfg)
    assert len(cohorts["train"]) == 5
    assert len(cohorts["validation"]) == 2
    assert len(cohorts["test"]) == 2

    # Verify disjointness and total
    train_set = set(cohorts["train"])
    val_set = set(cohorts["validation"])
    test_set = set(cohorts["test"])
    assert train_set & val_set == set()
    assert train_set & test_set == set()
    assert val_set & test_set == set()
    assert len(train_set | val_set | test_set) == 9

    # Verify full generation and disjointness assertion succeeds
    splits = generate_splits(cfg)
    assert_disjoint_splits(splits)
    manifest = splits["manifest"]
    assert manifest["cohorts"]["train"]["agent_count"] == 5
    assert manifest["cohorts"]["validation"]["agent_count"] == 2
    assert manifest["cohorts"]["test"]["agent_count"] == 2


def test_allocate_cohorts_three_agents_truly_zero_rejected(base_config):
    """Verify 3 agents under 60/20/20 splits are rejected due to truly zero global quotas."""
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["agents"] = 3
    cfg["simulation"]["agent_mix"] = {
        "normal": 1,
        "high_volume_honest": 1,
        "skimmers": 1,
    }
    cfg["simulation"]["customers"] = 30

    # Under 60/20/20, largest-remainder global quotas for 3 are train: 2, test: 1, validation: 0.
    # Validation has a truly zero quota, which must be rejected.
    with pytest.raises(ConfigError, match="Too few agents"):
        allocate_cohorts(cfg)

    with pytest.raises(ConfigError, match="Too few agents"):
        generate_splits(cfg)


def test_allocate_cohorts_three_agents_equal_split_succeeds(base_config):
    """Verify 3 agents with equal 1/3 split allocate exactly 1 agent per cohort."""
    cfg = copy.deepcopy(base_config)
    cfg["simulation"]["agents"] = 3
    cfg["simulation"]["agent_mix"] = {
        "normal": 1,
        "high_volume_honest": 1,
        "skimmers": 1,
    }
    cfg["simulation"]["agent_split"] = {
        "train": 1 / 3,
        "validation": 1 / 3,
        "test": 1 / 3,
    }
    cfg["simulation"]["customers"] = 30

    cohorts = allocate_cohorts(cfg)
    assert len(cohorts["train"]) == 1
    assert len(cohorts["validation"]) == 1
    assert len(cohorts["test"]) == 1

    splits = generate_splits(cfg)
    assert_disjoint_splits(splits)


def test_realistic_tiny_registry(base_config):
    """Verify tiny registry e.g. 30 agents (20 normal, 6 high, 4 skim) stratifies cleanly."""
    tiny_cfg = copy.deepcopy(base_config)
    tiny_cfg["simulation"]["agents"] = 30
    tiny_cfg["simulation"]["agent_mix"] = {
        "normal": 20,
        "high_volume_honest": 6,
        "skimmers": 4,
    }
    tiny_cfg["simulation"]["customers"] = 30

    cohorts = allocate_cohorts(tiny_cfg)
    assert len(cohorts["train"]) == 18
    assert len(cohorts["validation"]) == 6
    assert len(cohorts["test"]) == 6

    # Verify disjointness
    assert set(cohorts["train"]) & set(cohorts["validation"]) == set()
    assert set(cohorts["train"]) & set(cohorts["test"]) == set()
    assert set(cohorts["validation"]) & set(cohorts["test"]) == set()

    # Verify tiny splits generation and assertion passes
    splits = generate_splits(tiny_cfg)
    assert_disjoint_splits(splits)
    assert splits["manifest"]["cohorts"]["train"]["agent_count"] == 18
    assert splits["manifest"]["cohorts"]["validation"]["agent_count"] == 6
    assert splits["manifest"]["cohorts"]["test"]["agent_count"] == 6


def test_too_few_agents_rejected(base_config):
    """Verify configuration with too few agents to allocate disjoint cohorts is rejected."""
    bad_cfg = copy.deepcopy(base_config)
    bad_cfg["simulation"]["agents"] = 2
    bad_cfg["simulation"]["agent_mix"] = {
        "normal": 2,
        "high_volume_honest": 0,
        "skimmers": 0,
    }

    with pytest.raises(ConfigError, match="Too few agents"):
        allocate_cohorts(bad_cfg)

    with pytest.raises(ConfigError, match="Too few agents"):
        generate_splits(bad_cfg)


def test_full_default_splits_generation_counts_and_hashes(full_splits, base_config):
    """Keep one full default generation test verifying exact 180/60/60 and 12k/4k/4k counts,
    canonical config SHA-256, content checksums, and absence of invented aliases.
    """
    # Verify result structure has only {splits, manifest}
    assert set(full_splits.keys()) == {"splits", "manifest"}

    manifest = full_splits["manifest"]
    # Verify manifest has only {schema_version, synthetic, config_sha256, cohorts}
    assert set(manifest.keys()) == {"schema_version", "synthetic", "config_sha256", "cohorts"}
    assert manifest["synthetic"] is True
    assert manifest["schema_version"] == 1

    # Canonical config SHA-256
    expected_cfg_bytes = json.dumps(base_config, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    assert manifest["config_sha256"] == hashlib.sha256(expected_cfg_bytes).hexdigest()

    cohorts = manifest["cohorts"]
    assert set(cohorts.keys()) == {"train", "validation", "test"}

    expected_cohort_keys = {
        "seed",
        "agent_count",
        "customer_count",
        "agent_ids",
        "file",
        "content_sha256",
        "observations_file",
        "observations_sha256",
        "counts",
    }

    # Train
    train_info = cohorts["train"]
    assert set(train_info.keys()) == expected_cohort_keys
    assert train_info["seed"] == 42
    assert train_info["agent_count"] == 180
    assert train_info["customer_count"] == 12000
    assert len(train_info["agent_ids"]) == 180
    assert train_info["content_sha256"] == compute_dataset_checksum(
        full_splits["splits"]["train"]["dataset"]
    )

    # Validation
    val_info = cohorts["validation"]
    assert set(val_info.keys()) == expected_cohort_keys
    assert val_info["seed"] == 4242
    assert val_info["agent_count"] == 60
    assert val_info["customer_count"] == 4000
    assert len(val_info["agent_ids"]) == 60
    assert val_info["content_sha256"] == compute_dataset_checksum(
        full_splits["splits"]["validation"]["dataset"]
    )

    # Test
    test_info = cohorts["test"]
    assert set(test_info.keys()) == expected_cohort_keys
    assert test_info["seed"] == 2026
    assert test_info["agent_count"] == 60
    assert test_info["customer_count"] == 4000
    assert len(test_info["agent_ids"]) == 60
    assert test_info["content_sha256"] == compute_dataset_checksum(
        full_splits["splits"]["test"]["dataset"]
    )

    # Verify disjointness guard succeeds on full default splits
    assert_disjoint_splits(full_splits)
    assert_disjoint_splits(full_splits["splits"])


def test_positive_disjointness_on_small_splits(small_splits):
    """Verify assert_disjoint_splits succeeds on small splits fixture."""
    assert_disjoint_splits(small_splits)
    assert_disjoint_splits(small_splits["splits"])


def test_negative_contamination_agent(small_splits):
    """Verify injecting an agent across cohorts raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    train_agent = tampered["train"]["dataset"]["agents"][0]
    tampered["validation"]["dataset"]["agents"].append(train_agent)

    with pytest.raises(AssertionError, match="Agent contamination detected"):
        assert_disjoint_splits(tampered)


def test_negative_contamination_user(small_splits):
    """Verify injecting a user across cohorts raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    train_user = tampered["train"]["dataset"]["users"][0]
    tampered["validation"]["dataset"]["users"].append(train_user)

    with pytest.raises(AssertionError, match="User contamination detected"):
        assert_disjoint_splits(tampered)


def test_positive_no_transaction_crosses_cohort_customer_and_agent(small_splits):
    """Verify every transaction strictly pairs a customer and agent from the same cohort."""
    splits = small_splits["splits"]
    for c in ("train", "validation", "test"):
        cohort_users = {u["user_id"] for u in splits[c]["dataset"]["users"]}
        cohort_agents = {a["agent_id"] for a in splits[c]["dataset"]["agents"]}
        for t in splits[c]["dataset"]["transactions"]:
            assert t["user_id"] in cohort_users, f"User {t['user_id']} not in cohort {c}"
            if t.get("agent_id") is not None:
                assert t["agent_id"] in cohort_agents, f"Agent {t['agent_id']} not in cohort {c}"


def test_negative_contamination_txn_cross_cohort_user(small_splits):
    """Verify a transaction referencing a cross-cohort user raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    foreign_user_id = tampered["train"]["dataset"]["users"][0]["user_id"]

    for t in tampered["validation"]["dataset"]["transactions"]:
        t["user_id"] = foreign_user_id
        break

    with pytest.raises(AssertionError, match="references user .* outside its cohort"):
        assert_disjoint_splits(tampered)


def test_negative_contamination_txn_cross_cohort_agent(small_splits):
    """Verify a transaction referencing a cross-cohort agent raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    foreign_agent_id = tampered["train"]["dataset"]["agents"][0]["agent_id"]

    for t in tampered["validation"]["dataset"]["transactions"]:
        if t.get("agent_id") is not None:
            t["agent_id"] = foreign_agent_id
            break

    with pytest.raises(AssertionError, match="references agent .* outside its cohort"):
        assert_disjoint_splits(tampered)


def test_negative_contamination_session_cross_cohort_txn(small_splits):
    """Verify a session referencing a cross-cohort transaction raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    foreign_txn_id = tampered["train"]["dataset"]["transactions"][0]["txn_id"]

    for s in tampered["validation"]["dataset"]["sessions"]:
        if s.get("txn_id") is not None:
            s["txn_id"] = foreign_txn_id
            break

    with pytest.raises(AssertionError, match="references transaction .* outside its cohort"):
        assert_disjoint_splits(tampered)


def test_negative_contamination_cross_cohort_observation(small_splits):
    """Verify user observation pointing to cross-cohort home agent raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    foreign_agent_id = tampered["train"]["dataset"]["agents"][0]["agent_id"]

    obs = tampered["validation"]["observations"]
    first_uid = next(iter(obs["user_observations"]))
    obs["user_observations"][first_uid]["home_agent_id"] = foreign_agent_id

    with pytest.raises(AssertionError, match="cross-cohort home agent"):
        assert_disjoint_splits(tampered)


def test_negative_empty_cohort_rejected(small_splits):
    """Verify an empty cohort raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    tampered["test"]["dataset"]["agents"] = []

    with pytest.raises(AssertionError, match="Cohort 'test' has empty agents set"):
        assert_disjoint_splits(tampered)


def test_negative_missing_cohort_rejected(small_splits):
    """Verify missing cohort from splits raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    del tampered["test"]

    with pytest.raises(AssertionError, match="Disjoint splits require exactly cohorts"):
        assert_disjoint_splits(tampered)


def test_negative_repeated_dataset_seeds_rejected(small_splits):
    """Verify repeated seeds across cohorts raise AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    # Duplicate train seed into validation
    tampered["validation"]["dataset"]["seed"] = tampered["train"]["dataset"]["seed"]

    with pytest.raises(AssertionError, match="Cohort seeds must be three distinct integers"):
        assert_disjoint_splits(tampered)


def test_negative_session_user_mismatch_rejected(small_splits):
    """Verify session whose user does not own referenced transaction raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    val_ds = tampered["validation"]["dataset"]
    # Find session with transaction and change its user_id to a different cohort user
    sess = next(s for s in val_ds["sessions"] if s.get("txn_id") is not None)
    other_user = next(u["user_id"] for u in val_ds["users"] if u["user_id"] != sess["user_id"])
    sess["user_id"] = other_user

    with pytest.raises(
        AssertionError, match="belongs to user .* but references transaction .* owned by"
    ):
        assert_disjoint_splits(tampered)


def test_negative_transaction_observation_key_mismatch_rejected(small_splits):
    """Verify transaction observation with key mismatch raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    obs = tampered["validation"]["observations"]
    key = next(iter(obs["transaction_observations"]))
    obs["transaction_observations"]["99999999"] = obs["transaction_observations"].pop(key)

    with pytest.raises(
        AssertionError, match="Transaction observation key .* does not match its txn_id"
    ):
        assert_disjoint_splits(tampered)


def test_negative_transaction_observation_missing_txn_rejected(small_splits):
    """Verify transaction observation referencing nonexistent txn_id raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    obs = tampered["validation"]["observations"]
    key = "88888888"
    obs["transaction_observations"][key] = {
        "txn_id": 88888888,
        "user_id": tampered["validation"]["dataset"]["users"][0]["user_id"],
        "agent_id": tampered["validation"]["dataset"]["agents"][0]["agent_id"],
    }

    with pytest.raises(AssertionError, match="not found in cohort transactions"):
        assert_disjoint_splits(tampered)


def test_negative_transaction_observation_user_mismatch_rejected(small_splits):
    """Verify transaction observation with mismatched user_id raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    obs = tampered["validation"]["observations"]
    first_tobs = next(iter(obs["transaction_observations"].values()))
    val_users = tampered["validation"]["dataset"]["users"]
    other_uid = next(u["user_id"] for u in val_users if u["user_id"] != first_tobs["user_id"])
    first_tobs["user_id"] = other_uid

    with pytest.raises(AssertionError, match="does not match actual transaction user_id"):
        assert_disjoint_splits(tampered)


def test_negative_transaction_observation_agent_mismatch_rejected(small_splits):
    """Verify transaction observation with mismatched agent_id raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    obs = tampered["validation"]["observations"]
    first_tobs = next(iter(obs["transaction_observations"].values()))
    val_agents = tampered["validation"]["dataset"]["agents"]
    other_aid = next(a["agent_id"] for a in val_agents if a["agent_id"] != first_tobs["agent_id"])
    first_tobs["agent_id"] = other_aid

    with pytest.raises(AssertionError, match="does not match actual transaction agent_id"):
        assert_disjoint_splits(tampered)


def test_negative_duplicate_user_id_within_cohort_rejected(small_splits):
    """Verify duplicate user_id within a cohort raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    val_users = tampered["validation"]["dataset"]["users"]
    val_users.append(copy.deepcopy(val_users[0]))

    with pytest.raises(AssertionError, match="Duplicate user IDs found within cohort"):
        assert_disjoint_splits(tampered)


def test_negative_duplicate_agent_id_within_cohort_rejected(small_splits):
    """Verify duplicate agent_id within a cohort raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    val_agents = tampered["validation"]["dataset"]["agents"]
    val_agents.append(copy.deepcopy(val_agents[0]))

    with pytest.raises(AssertionError, match="Duplicate agent IDs found within cohort"):
        assert_disjoint_splits(tampered)


def test_negative_duplicate_txn_id_within_cohort_rejected(small_splits):
    """Verify duplicate txn_id within a cohort raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    val_txns = tampered["validation"]["dataset"]["transactions"]
    val_txns.append(copy.deepcopy(val_txns[0]))

    with pytest.raises(AssertionError, match="Duplicate transaction IDs found within cohort"):
        assert_disjoint_splits(tampered)


def test_negative_duplicate_session_id_within_cohort_rejected(small_splits):
    """Verify duplicate session_id within a cohort raises AssertionError."""
    tampered = copy.deepcopy(small_splits["splits"])
    val_sessions = tampered["validation"]["dataset"]["sessions"]
    val_sessions.append(copy.deepcopy(val_sessions[0]))

    with pytest.raises(AssertionError, match="Duplicate session IDs found within cohort"):
        assert_disjoint_splits(tampered)


def test_negative_guard_input_rejected_if_not_full_result_or_exact_three_cohorts(small_splits):
    """Verify input to assert_disjoint_splits must be full result or exact three-cohort mapping."""
    bad_input = {"arbitrary_key": "some_value"}
    with pytest.raises(AssertionError, match="Input to assert_disjoint_splits must be full result"):
        assert_disjoint_splits(bad_input)

    # Alias keys like datasets/observations at root without splits/manifest rejected
    bad_aliases = {
        "train": small_splits["splits"]["train"],
        "validation": small_splits["splits"]["validation"],
        "test": small_splits["splits"]["test"],
        "datasets": {},
    }
    with pytest.raises(AssertionError, match="Input to assert_disjoint_splits must be full result"):
        assert_disjoint_splits(bad_aliases)


def test_generate_splits_repeat_hashes_identical(small_config):
    """Verify running generate_splits twice yields 100% byte-identical content and hashes."""
    s1 = generate_splits(small_config)
    s2 = generate_splits(small_config)

    for c in ("train", "validation", "test"):
        b1_ds = json.dumps(
            s1["splits"][c]["dataset"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        b2_ds = json.dumps(
            s2["splits"][c]["dataset"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        assert b1_ds == b2_ds
        assert hashlib.sha256(b1_ds).hexdigest() == hashlib.sha256(b2_ds).hexdigest()

        b1_obs = json.dumps(
            s1["splits"][c]["observations"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        b2_obs = json.dumps(
            s2["splits"][c]["observations"], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        assert b1_obs == b2_obs

    b1_m = json.dumps(s1["manifest"], sort_keys=True, indent=2).encode("utf-8")
    b2_m = json.dumps(s2["manifest"], sort_keys=True, indent=2).encode("utf-8")
    assert b1_m == b2_m


def test_write_splits_files_valid_and_loadable(tmp_path, small_splits):
    """Verify write_splits writes all 7 files and main JSON files pass validate_dataset."""
    write_splits(small_splits, tmp_path)

    expected_files = [
        tmp_path / "train.json",
        tmp_path / "train.observations.json",
        tmp_path / "validation.json",
        tmp_path / "validation.observations.json",
        tmp_path / "test.json",
        tmp_path / "test.observations.json",
        tmp_path / "manifest.json",
    ]
    for p in expected_files:
        assert p.is_file(), f"Expected file {p} does not exist"

    for c in ("train", "validation", "test"):
        with open(tmp_path / f"{c}.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        validate_dataset(data)


def test_cli_split_subcommand(tmp_path, small_config):
    """Verify CLI 'split' command generates all split files and exits 0."""
    cfg_file = tmp_path / "config.yaml"
    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(small_config, f)

    out_dir = tmp_path / "splits_output"
    exit_code = cli_main(["split", "--config", str(cfg_file), "--output-dir", str(out_dir)])
    assert exit_code == 0

    assert (out_dir / "train.json").is_file()
    assert (out_dir / "validation.json").is_file()
    assert (out_dir / "test.json").is_file()
    assert (out_dir / "manifest.json").is_file()


def test_in_memory_split_aggregation_counts_and_no_collision(full_splits):
    """Verify combined splits yield exact 20,000 users and 300 agents with zero ID collisions."""
    train_data = full_splits["splits"]["train"]["dataset"]
    val_data = full_splits["splits"]["validation"]["dataset"]
    test_data = full_splits["splits"]["test"]["dataset"]

    # Exact customer counts
    assert len(train_data["users"]) == 12000
    assert len(val_data["users"]) == 4000
    assert len(test_data["users"]) == 4000

    # Combined users
    all_users = (
        {u["user_id"] for u in train_data["users"]}
        | {u["user_id"] for u in val_data["users"]}
        | {u["user_id"] for u in test_data["users"]}
    )
    assert len(all_users) == 20000

    # Exact agent counts
    assert len(train_data["agents"]) == 180
    assert len(val_data["agents"]) == 60
    assert len(test_data["agents"]) == 60

    # Combined agents
    all_agents = (
        {a["agent_id"] for a in train_data["agents"]}
        | {a["agent_id"] for a in val_data["agents"]}
        | {a["agent_id"] for a in test_data["agents"]}
    )
    assert len(all_agents) == 300

    # Combined transaction IDs
    all_txns = (
        {t["txn_id"] for t in train_data["transactions"]}
        | {t["txn_id"] for t in val_data["transactions"]}
        | {t["txn_id"] for t in test_data["transactions"]}
    )
    expected_txn_count = (
        len(train_data["transactions"])
        + len(val_data["transactions"])
        + len(test_data["transactions"])
    )
    assert len(all_txns) == expected_txn_count

    # Combined session IDs
    all_sessions = (
        {s["session_id"] for s in train_data["sessions"]}
        | {s["session_id"] for s in val_data["sessions"]}
        | {s["session_id"] for s in test_data["sessions"]}
    )
    expected_session_count = (
        len(train_data["sessions"])
        + len(val_data["sessions"])
        + len(test_data["sessions"])
    )
    assert len(all_sessions) == expected_session_count
