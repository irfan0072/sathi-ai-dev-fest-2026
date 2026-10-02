"""Disjoint agent and seed split tooling for Sathi.

Builds canonical stable global agent registry and allocates train, validation,
and test cohorts using largest-remainder allocation and deterministic shuffling
from seed_train. Enforces complete cohort isolation across agents, users,
transactions, and sessions.
"""

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from app.data.config import ConfigError, load_config, validate_config
from app.data.database import ValidationError, validate_dataset
from app.data.generator import build_canonical_agent_registry, generate_dataset


def allocate_largest_remainder(total: int, ratios: dict[str, float]) -> dict[str, int]:
    """Allocate an integer total across cohorts using the largest-remainder method.

    Guarantees that the sum of allocated integers exactly equals total.
    Ties in fractional remainders are broken stably by cohort key.
    """
    if total < 0:
        raise ValueError(f"Total must be non-negative, got {total}")
    raw = {k: total * v for k, v in ratios.items()}
    floored = {k: math.floor(val) for k, val in raw.items()}
    remainder = total - sum(floored.values())
    priority = sorted(ratios.keys(), key=lambda k: (-(raw[k] - floored[k]), k))
    for k in priority[:remainder]:
        floored[k] += 1
    return floored


def allocate_cohorts(
    config: dict[str, Any] | None = None,
    canonical_agents: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    """Allocate canonical agents into train, validation, and test cohorts.

    Stratifies agent types where possible using largest-remainder allocation.
    Shuffles deterministically from seed_train.
    Requires explicit non-empty cohorts. Rejects if too few agents to allocate
    valid non-empty disjoint cohorts.
    """
    if config is None:
        cfg = load_config()
    else:
        cfg = validate_config(config)

    sim_cfg = cfg["simulation"]
    agent_split = sim_cfg["agent_split"]
    seed_train = sim_cfg["seed_train"]
    total_agents = sim_cfg["agents"]

    cohort_names = list(agent_split.keys())
    if len(cohort_names) < 2:
        raise ConfigError(f"agent_split must define multiple cohorts, got {cohort_names}")

    if total_agents < len(cohort_names):
        raise ConfigError(
            f"Too few agents ({total_agents}) to allocate valid non-empty disjoint cohorts "
            f"for {cohort_names}"
        )

    global_quotas = allocate_largest_remainder(total_agents, agent_split)
    for c in cohort_names:
        if global_quotas[c] <= 0:
            raise ConfigError(
                f"Too few agents ({total_agents}) to allocate non-empty cohort for '{c}' "
                f"under agent_split {agent_split}"
            )

    if canonical_agents is None:
        canonical_agents = build_canonical_agent_registry(cfg)

    if len(canonical_agents) != total_agents:
        raise ConfigError(
            f"Canonical agents count ({len(canonical_agents)}) does not match "
            f"simulation.agents ({total_agents})"
        )

    # Group canonical agents by agent_type
    agents_by_type: dict[str, list[dict[str, Any]]] = {}
    for a in canonical_agents:
        agents_by_type.setdefault(a["agent_type"], []).append(a)

    known_order = ["normal", "high_volume_honest", "skimmer"]
    type_order = [t for t in known_order if t in agents_by_type] + sorted(
        [t for t in agents_by_type if t not in known_order]
    )

    cohort_agent_ids: dict[str, list[str]] = {c: [] for c in cohort_names}
    rng = random.Random(seed_train)

    for atype in type_order:
        type_agents = [a["agent_id"] for a in agents_by_type[atype]]
        rng.shuffle(type_agents)
        type_quotas = allocate_largest_remainder(len(type_agents), agent_split)
        idx = 0
        for c in cohort_names:
            cnt = type_quotas[c]
            cohort_agent_ids[c].extend(type_agents[idx : idx + cnt])
            idx += cnt

    # Deterministically reconcile stratified allocations to global quotas, minimizing movement
    while True:
        surplus_cohorts = [
            c for c in cohort_names if len(cohort_agent_ids[c]) > global_quotas[c]
        ]
        deficit_cohorts = [
            c for c in cohort_names if len(cohort_agent_ids[c]) < global_quotas[c]
        ]
        if not surplus_cohorts or not deficit_cohorts:
            break
        c_from = surplus_cohorts[0]
        c_to = deficit_cohorts[0]
        moved = cohort_agent_ids[c_from].pop()
        cohort_agent_ids[c_to].append(moved)

    # Verify every cohort is explicitly non-empty
    for c, aids in cohort_agent_ids.items():
        if not aids:
            raise ConfigError(
                f"Too few agents to allocate valid non-empty disjoint cohort for '{c}'"
            )
        aids.sort()

    return cohort_agent_ids


def _extract_split_datasets(
    splits: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Helper to extract cohort datasets and observations from allowed guard structures.

    Allowed guard inputs:
    1. Full result mapping: exactly keys {'splits', 'manifest'}
    2. Exact three-cohort mapping: exactly keys {'train', 'validation', 'test'}
    """
    if not isinstance(splits, dict):
        raise AssertionError(f"Expected splits mapping, got {type(splits).__name__}")

    split_keys = set(splits.keys())
    if split_keys == {"splits", "manifest"}:
        cohort_mapping = splits["splits"]
        if not isinstance(cohort_mapping, dict):
            raise AssertionError("splits['splits'] must be a dictionary")
    elif split_keys == {"train", "validation", "test"}:
        cohort_mapping = splits
    else:
        raise AssertionError(
            "Input to assert_disjoint_splits must be full result {splits, manifest} "
            "or exact three-cohort mapping. Disjoint splits require exactly cohorts "
            f"('train', 'validation', 'test'), got keys: {sorted(split_keys)}"
        )

    expected_cohorts = ("train", "validation", "test")
    if tuple(sorted(cohort_mapping.keys())) != tuple(sorted(expected_cohorts)):
        raise AssertionError(
            f"Disjoint splits require exactly cohorts ('train', 'validation', 'test'), "
            f"got {sorted(cohort_mapping.keys())}"
        )

    datasets: dict[str, dict[str, Any]] = {}
    observations: dict[str, Any] = {}

    for c in expected_cohorts:
        val = cohort_mapping[c]
        if isinstance(val, dict):
            if "dataset" in val and isinstance(val["dataset"], dict):
                datasets[c] = val["dataset"]
                observations[c] = val.get("observations")
            elif "users" in val and isinstance(val["users"], list):
                datasets[c] = val
                observations[c] = getattr(val, "observations", None)
            else:
                raise AssertionError(
                    f"Cohort '{c}' must contain dataset dictionary or mapping with 'dataset' key"
                )
        elif hasattr(val, "observations"):
            datasets[c] = val
            observations[c] = val.observations
        else:
            raise AssertionError(f"Cohort '{c}' has unsupported structure: {type(val)}")

    return datasets, observations


def assert_disjoint_splits(splits: Any) -> None:
    """Verify agent and user sets, txn agent references, and session txn cohort invariants.

    Verifies:
    1. Splits input is full result or exact three-cohort mapping ('train', 'validation', 'test').
    2. Exactly three distinct non-negative integer seeds across cohorts.
    3. Agent cohorts, user sets, transaction IDs, session IDs are disjoint across splits.
    4. No duplicate IDs within any cohort.
    5. All transaction agent_id references point strictly to agents in own cohort.
    6. All transactions belong to users in own cohort.
    7. All sessions belong to users and txns in own cohort, session user owns txn.
    8. User metadata / observations only reference own cohort agents.
    9. Transaction observations keys/txn_id/user_id/agent_id match same cohort's actual transaction.
    10. Full schema and relational validity via validate_dataset.

    Raises AssertionError upon any contamination, duplicate ID, or invariant violation.
    """
    datasets, cohort_obs = _extract_split_datasets(splits)
    cohort_names = ["train", "validation", "test"]

    # Verify seeds: exactly three distinct nonnegative integer seeds
    cohort_seeds: dict[str, int] = {}
    for c in cohort_names:
        s = datasets[c].get("seed")
        if type(s) is not int or isinstance(s, bool) or not (0 <= s < 2**31):
            raise AssertionError(f"Cohort '{c}' has missing or invalid dataset seed: {s!r}")
        cohort_seeds[c] = s

    if len(set(cohort_seeds.values())) != 3:
        raise AssertionError(f"Cohort seeds must be three distinct integers, got {cohort_seeds}")

    cohort_agents: dict[str, set[str]] = {}
    cohort_users: dict[str, set[str]] = {}
    cohort_txns: dict[str, set[int]] = {}
    cohort_sessions: dict[str, set[int]] = {}

    for c in cohort_names:
        data = datasets[c]
        u_list = data.get("users", [])
        a_list = data.get("agents", [])
        t_list = data.get("transactions", [])
        s_list = data.get("sessions", [])

        if not a_list:
            raise AssertionError(f"Cohort '{c}' has empty agents set")
        if not u_list:
            raise AssertionError(f"Cohort '{c}' has empty users set")

        # Duplicate ID checks within each cohort
        u_ids = [u["user_id"] for u in u_list]
        if len(u_ids) != len(set(u_ids)):
            raise AssertionError(f"Duplicate user IDs found within cohort '{c}'")
        a_ids = [a["agent_id"] for a in a_list]
        if len(a_ids) != len(set(a_ids)):
            raise AssertionError(f"Duplicate agent IDs found within cohort '{c}'")
        t_ids = [t["txn_id"] for t in t_list]
        if len(t_ids) != len(set(t_ids)):
            raise AssertionError(f"Duplicate transaction IDs found within cohort '{c}'")
        s_ids = [s["session_id"] for s in s_list]
        if len(s_ids) != len(set(s_ids)):
            raise AssertionError(f"Duplicate session IDs found within cohort '{c}'")

        cohort_agents[c] = set(a_ids)
        cohort_users[c] = set(u_ids)
        cohort_txns[c] = set(t_ids)
        cohort_sessions[c] = set(s_ids)

    # 1. Pairwise disjointness across all cohort pairs
    for i in range(len(cohort_names)):
        for j in range(i + 1, len(cohort_names)):
            c1, c2 = cohort_names[i], cohort_names[j]

            shared_agents = cohort_agents[c1] & cohort_agents[c2]
            if shared_agents:
                raise AssertionError(
                    f"Agent contamination detected between cohorts '{c1}' and '{c2}': "
                    f"{sorted(shared_agents)}"
                )

            shared_users = cohort_users[c1] & cohort_users[c2]
            if shared_users:
                raise AssertionError(
                    f"User contamination detected between cohorts '{c1}' and '{c2}': "
                    f"{sorted(shared_users)}"
                )

            shared_txns = cohort_txns[c1] & cohort_txns[c2]
            if shared_txns:
                raise AssertionError(
                    f"Transaction ID contamination between cohorts '{c1}' and '{c2}': "
                    f"{sorted(shared_txns)}"
                )

            shared_sessions = cohort_sessions[c1] & cohort_sessions[c2]
            if shared_sessions:
                raise AssertionError(
                    f"Session ID contamination between cohorts '{c1}' and '{c2}': "
                    f"{sorted(shared_sessions)}"
                )

    # 2. Relational cohort integrity within each cohort
    for c in cohort_names:
        data = datasets[c]
        agents = cohort_agents[c]
        users = cohort_users[c]
        txns = cohort_txns[c]
        txn_map = {t["txn_id"]: t for t in data.get("transactions", [])}

        for t in data.get("transactions", []):
            tid = t["txn_id"]
            uid = t["user_id"]
            if uid not in users:
                raise AssertionError(
                    f"Transaction {tid} in cohort '{c}' references user '{uid}' "
                    f"outside its cohort"
                )
            aid = t.get("agent_id")
            if aid is not None and aid not in agents:
                raise AssertionError(
                    f"Transaction {tid} in cohort '{c}' references agent '{aid}' "
                    f"outside its cohort"
                )

        for s in data.get("sessions", []):
            sid = s["session_id"]
            uid = s["user_id"]
            if uid not in users:
                raise AssertionError(
                    f"Session {sid} in cohort '{c}' references user '{uid}' "
                    f"outside its cohort"
                )
            tid = s.get("txn_id")
            if tid is not None:
                if tid not in txns:
                    raise AssertionError(
                        f"Session {sid} in cohort '{c}' references transaction {tid} "
                        f"outside its cohort"
                    )
                # Verify each session's user owns its referenced transaction
                ref_txn = txn_map[tid]
                if ref_txn["user_id"] != uid:
                    raise AssertionError(
                        f"Session {sid} in cohort '{c}' belongs to user '{uid}' "
                        f"but references transaction {tid} owned by user '{ref_txn['user_id']}'"
                    )

    # 3. Sidecar observations verification if present
    for c in cohort_names:
        obs = cohort_obs.get(c)
        if obs and isinstance(obs, dict):
            # User observations check
            user_obs = obs.get("user_observations", {})
            for uid, meta in user_obs.items():
                if uid not in cohort_users[c]:
                    raise AssertionError(
                        f"Observation user '{uid}' in cohort '{c}' is outside cohort users"
                    )
                home_aid = meta.get("home_agent_id")
                if home_aid and home_aid not in cohort_agents[c]:
                    raise AssertionError(
                        f"Observation user '{uid}' in cohort '{c}' references "
                        f"cross-cohort home agent '{home_aid}'"
                    )

            # Transaction observations check
            txn_obs = obs.get("transaction_observations", {})
            txn_map = {t["txn_id"]: t for t in datasets[c].get("transactions", [])}
            for key, tobs in txn_obs.items():
                obs_tid = tobs.get("txn_id")
                if str(obs_tid) != str(key):
                    raise AssertionError(
                        f"Transaction observation key '{key}' does not match "
                        f"its txn_id {obs_tid} in cohort '{c}'"
                    )
                if obs_tid not in txn_map:
                    raise AssertionError(
                        f"Transaction observation {obs_tid} in cohort '{c}' "
                        "not found in cohort transactions"
                    )
                actual_txn = txn_map[obs_tid]
                obs_uid = tobs.get("user_id")
                if obs_uid != actual_txn["user_id"]:
                    raise AssertionError(
                        f"Transaction observation {obs_tid} in cohort '{c}' has "
                        f"user_id '{obs_uid}' which does not match actual "
                        f"transaction user_id '{actual_txn['user_id']}'"
                    )
                obs_aid = tobs.get("agent_id")
                if obs_aid != actual_txn["agent_id"]:
                    raise AssertionError(
                        f"Transaction observation {obs_tid} in cohort '{c}' has "
                        f"agent_id '{obs_aid}' which does not match actual "
                        f"transaction agent_id '{actual_txn['agent_id']}'"
                    )

    # 4. Reuse validate_dataset after readable contamination checks
    for c in cohort_names:
        try:
            validate_dataset(datasets[c])
        except ValidationError as exc:
            raise AssertionError(f"Cohort '{c}' failed schema validation: {exc}") from exc


def generate_splits(
    config: dict[str, Any] | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Generate disjoint train, validation, and test dataset splits with manifest.

    Parameters:
        config: Simulation configuration dictionary (loads data/config.yaml if None).
        output_dir: Optional directory to persist generated JSON splits and manifest.

    Returns:
        Mapping containing split datasets, observations, and canonical manifest.
    """
    if config is None:
        cfg = load_config()
    else:
        cfg = validate_config(config)

    sim_cfg = cfg["simulation"]
    agent_split = sim_cfg["agent_split"]
    seed_train = sim_cfg["seed_train"]
    seed_val = sim_cfg["seed_validation"]
    seed_test = sim_cfg["seed_test"]
    total_customers = sim_cfg["customers"]

    cohort_seeds = {
        "train": seed_train,
        "validation": seed_val,
        "test": seed_test,
    }
    for c_name, s_val in cohort_seeds.items():
        if type(s_val) is not int or isinstance(s_val, bool) or s_val < 0 or s_val >= 2**31:
            raise ConfigError(
                f"simulation.{c_name} seed must be a nonnegative 31-bit integer, got {s_val!r}"
            )
    if len(set(cohort_seeds.values())) != len(cohort_seeds):
        raise ConfigError(f"Cohort seeds {cohort_seeds} must all be distinct")

    # 1. Build canonical stable global agent registry once
    canonical_agents = build_canonical_agent_registry(cfg)

    # 2. Allocate disjoint agent cohorts
    cohort_agent_ids = allocate_cohorts(cfg, canonical_agents=canonical_agents)

    # 3. Allocate customer counts
    customer_counts = allocate_largest_remainder(total_customers, agent_split)
    for c_name, c_cnt in customer_counts.items():
        if c_cnt <= 0:
            raise ConfigError(
                f"Too few customers ({total_customers}) to allocate non-empty cohort '{c_name}'"
            )

    # 4. Generate datasets and observations per cohort
    splits_dict: dict[str, dict[str, Any]] = {}
    for c_name in ("train", "validation", "test"):
        ds, obs = generate_dataset(
            config=cfg,
            seed=cohort_seeds[c_name],
            agent_ids=cohort_agent_ids[c_name],
            customers=customer_counts[c_name],
            return_observations=True,
            canonical_agents=canonical_agents,
        )
        validate_dataset(ds)
        splits_dict[c_name] = {
            "dataset": ds,
            "observations": obs,
        }

    # 5. Assert strict disjointness and integrity
    assert_disjoint_splits(splits_dict)

    # 6. Build canonical split manifest
    config_bytes = json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")
    config_sha256 = hashlib.sha256(config_bytes).hexdigest()

    manifest_cohorts: dict[str, Any] = {}
    for c_name in ("train", "validation", "test"):
        ds = splits_dict[c_name]["dataset"]
        obs = splits_dict[c_name]["observations"]

        ds_bytes = json.dumps(ds, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ds_sha256 = hashlib.sha256(ds_bytes).hexdigest()

        obs_bytes = json.dumps(obs, sort_keys=True, separators=(",", ":")).encode("utf-8")
        obs_sha256 = hashlib.sha256(obs_bytes).hexdigest()

        c_info = {
            "seed": cohort_seeds[c_name],
            "agent_count": len(cohort_agent_ids[c_name]),
            "customer_count": customer_counts[c_name],
            "agent_ids": cohort_agent_ids[c_name],
            "file": f"{c_name}.json",
            "content_sha256": ds_sha256,
            "observations_file": f"{c_name}.observations.json",
            "observations_sha256": obs_sha256,
            "counts": {
                "agents": len(cohort_agent_ids[c_name]),
                "customers": customer_counts[c_name],
                "users": len(ds["users"]),
                "transactions": len(ds["transactions"]),
                "sessions": len(ds["sessions"]),
            },
        }
        manifest_cohorts[c_name] = c_info

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "synthetic": True,
        "config_sha256": config_sha256,
        "cohorts": manifest_cohorts,
    }

    result = {
        "splits": splits_dict,
        "manifest": manifest,
    }

    if output_dir is not None:
        write_splits(result, output_dir)

    return result


def write_splits(
    splits_result: dict[str, Any],
    output_dir: Path | str,
) -> dict[str, Path]:
    """Persist split datasets, observations, and manifest to output directory.

    Files written:
    - train.json, train.observations.json
    - validation.json, validation.observations.json
    - test.json, test.observations.json
    - manifest.json
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    splits = splits_result["splits"]
    manifest = splits_result["manifest"]

    for c_name in ("train", "validation", "test"):
        ds = splits[c_name]["dataset"]
        obs = splits[c_name]["observations"]

        ds_path = out_path / f"{c_name}.json"
        obs_path = out_path / f"{c_name}.observations.json"

        ds_bytes = json.dumps(ds, sort_keys=True, separators=(",", ":")).encode("utf-8")
        obs_bytes = json.dumps(obs, sort_keys=True, separators=(",", ":")).encode("utf-8")

        ds_path.write_bytes(ds_bytes)
        obs_path.write_bytes(obs_bytes)

        written[f"{c_name}_dataset"] = ds_path
        written[f"{c_name}_observations"] = obs_path

    manifest_path = out_path / "manifest.json"
    manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    written["manifest"] = manifest_path

    return written
