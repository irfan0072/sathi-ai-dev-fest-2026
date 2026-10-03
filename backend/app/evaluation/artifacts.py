"""Artifact management, validation, and serialization utilities for Sathi evaluation.

Provides:
- Strict split manifest and shifted test metadata validation with fail-closed semantics.
- Secure model artifact loader with SHA-256 checksum and schema enforcement.
- Curated deployment bundle export and loading for offline serving and demo UI.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.data.database import validate_dataset
from app.data.splits import assert_disjoint_splits
from app.features.guard import assert_feature_columns

if TYPE_CHECKING:
    from app.models.agent_model import AgentAnomalyDetector
    from app.models.assisted_model import AssistedUserClassifier


class ArtifactError(Exception):
    """Base exception for evaluation and model artifact errors."""


class ArtifactUnavailableError(ArtifactError):
    """Raised when a requested artifact or manifest is missing or inaccessible."""


class ArtifactVerificationError(ArtifactError):
    """Raised when an artifact fails cryptographic hash, schema, or integrity validation."""


class SanityCeilingExceededError(ArtifactError):
    """Raised when validation metrics exceed configured sanity ceiling before test evaluation."""


def validate_manifest_and_metadata(
    splits_dir: Path | str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate split manifest, checksums, foreign keys, disjointness, and shifted metadata.

    Fails closed on:
    - Missing splits directory or manifest files.
    - Unsupported schema_version or missing synthetic flag.
    - Config SHA-256 mismatch (if config is supplied).
    - Content or observations SHA-256 mismatch for any split.
    - Declared counts, seeds, or cohort agent IDs mismatching dataset contents.
    - Relational foreign key violations in standard or shifted observations.
    - Pairwise agent or customer contamination across train/validation/test.
    - Shifted test agent cohort mismatching standard test cohort.
    - Shifted test contaminating train or validation cohorts.
    - Shifted test declared counts or seeds mismatching dataset contents.

    Returns:
        Mapping containing parsed manifest, metadata, datasets, and observations.
    """
    s_dir = Path(splits_dir)
    if not s_dir.is_dir():
        raise ArtifactUnavailableError(
            f"Splits directory does not exist or is not a directory: {s_dir}"
        )

    manifest_path = s_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ArtifactUnavailableError(
            f"Missing manifest.json in splits directory: {manifest_path}"
        )

    shifted_meta_path = s_dir / "test_shifted.meta.json"
    if not shifted_meta_path.is_file():
        raise ArtifactUnavailableError(
            f"Missing test_shifted.meta.json in splits directory: {shifted_meta_path}"
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ArtifactVerificationError(f"Failed to parse manifest.json: {exc}") from exc

    for req_key in ("schema_version", "synthetic", "config_sha256", "cohorts"):
        if req_key not in manifest:
            raise ArtifactVerificationError(f"manifest.json missing required key '{req_key}'")

    if manifest.get("schema_version") != 1:
        raise ArtifactVerificationError(
            f"Unsupported manifest schema_version: {manifest.get('schema_version')}"
        )
    if manifest.get("synthetic") is not True:
        raise ArtifactVerificationError("Manifest must declare synthetic=true")

    cohorts = manifest["cohorts"]
    for c_name in ("train", "validation", "test"):
        if c_name not in cohorts:
            raise ArtifactVerificationError(f"manifest.json missing cohort '{c_name}'")

    # 1. Config hash and configured cohort seed/allocation verification
    if config is not None:
        cfg_bytes = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected_cfg_sha = hashlib.sha256(cfg_bytes).hexdigest()
        if manifest["config_sha256"] != expected_cfg_sha:
            raise ArtifactVerificationError(
                f"Manifest config_sha256 mismatch: expected {expected_cfg_sha}, "
                f"got {manifest['config_sha256']}"
            )
        sim_cfg = config.get("simulation", {})
        if "seed_train" in sim_cfg and cohorts["train"].get("seed") != sim_cfg["seed_train"]:
            raise ArtifactVerificationError("Train cohort seed mismatch with config seed_train")
        if (
            "seed_validation" in sim_cfg
            and cohorts["validation"].get("seed") != sim_cfg["seed_validation"]
        ):
            raise ArtifactVerificationError(
                "Validation cohort seed mismatch with config seed_validation"
            )
        if "seed_test" in sim_cfg and cohorts["test"].get("seed") != sim_cfg["seed_test"]:
            raise ArtifactVerificationError("Test cohort seed mismatch with config seed_test")

    # 2. Check each standard split file, content hash, observations hash, counts, and FKs
    datasets: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}
    splits_dict: dict[str, dict[str, Any]] = {}

    for c_name in ("train", "validation", "test"):
        c_info = cohorts[c_name]
        ds_file = s_dir / c_info["file"]
        if not ds_file.is_file():
            raise ArtifactUnavailableError(f"Dataset file missing for cohort '{c_name}': {ds_file}")

        ds_raw_bytes = ds_file.read_bytes()
        actual_content_sha = hashlib.sha256(ds_raw_bytes).hexdigest()
        if actual_content_sha != c_info["content_sha256"]:
            try:
                parsed_temp = json.loads(ds_raw_bytes.decode("utf-8"))
                canon_bytes = json.dumps(parsed_temp, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
                if hashlib.sha256(canon_bytes).hexdigest() != c_info["content_sha256"]:
                    raise ArtifactVerificationError(
                        f"Content SHA-256 mismatch for cohort '{c_name}': "
                        f"manifest={c_info['content_sha256']}, actual={actual_content_sha}"
                    )
            except Exception as exc:
                raise ArtifactVerificationError(
                    f"Content SHA-256 mismatch for cohort '{c_name}': "
                    f"manifest={c_info['content_sha256']}, actual={actual_content_sha}"
                ) from exc

        obs_file = s_dir / c_info["observations_file"]
        if not obs_file.is_file():
            raise ArtifactUnavailableError(
                f"Observations file missing for cohort '{c_name}': {obs_file}"
            )

        obs_raw_bytes = obs_file.read_bytes()
        actual_obs_sha = hashlib.sha256(obs_raw_bytes).hexdigest()
        if actual_obs_sha != c_info["observations_sha256"]:
            try:
                parsed_obs_temp = json.loads(obs_raw_bytes.decode("utf-8"))
                canon_obs_bytes = json.dumps(
                    parsed_obs_temp, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                if hashlib.sha256(canon_obs_bytes).hexdigest() != c_info["observations_sha256"]:
                    raise ArtifactVerificationError(
                        f"Observations SHA-256 mismatch for cohort '{c_name}': "
                        f"manifest={c_info['observations_sha256']}, actual={actual_obs_sha}"
                    )
            except Exception as exc:
                raise ArtifactVerificationError(
                    f"Observations SHA-256 mismatch for cohort '{c_name}': "
                    f"manifest={c_info['observations_sha256']}, actual={actual_obs_sha}"
                ) from exc

        ds_data = json.loads(ds_raw_bytes.decode("utf-8"))
        obs_data = json.loads(obs_raw_bytes.decode("utf-8"))

        # Verify declared counts
        counts = c_info.get("counts", {})
        if len(ds_data.get("users", [])) != counts.get("users"):
            raise ArtifactVerificationError(
                f"User count mismatch in '{c_name}': declared {counts.get('users')}, "
                f"actual {len(ds_data.get('users', []))}"
            )
        if len(ds_data.get("agents", [])) != counts.get("agents"):
            raise ArtifactVerificationError(
                f"Agent count mismatch in '{c_name}': declared {counts.get('agents')}, "
                f"actual {len(ds_data.get('agents', []))}"
            )
        if len(ds_data.get("transactions", [])) != counts.get("transactions"):
            raise ArtifactVerificationError(
                f"Transaction count mismatch in '{c_name}': declared {counts.get('transactions')}, "
                f"actual {len(ds_data.get('transactions', []))}"
            )
        if len(ds_data.get("sessions", [])) != counts.get("sessions"):
            raise ArtifactVerificationError(
                f"Session count mismatch in '{c_name}': declared {counts.get('sessions')}, "
                f"actual {len(ds_data.get('sessions', []))}"
            )

        if ds_data.get("seed") != c_info.get("seed"):
            raise ArtifactVerificationError(
                f"Dataset seed mismatch in '{c_name}': manifest={c_info.get('seed')}, "
                f"dataset={ds_data.get('seed')}"
            )

        actual_agent_ids = sorted([a["agent_id"] for a in ds_data.get("agents", [])])
        if actual_agent_ids != sorted(c_info.get("agent_ids", [])):
            raise ArtifactVerificationError(
                f"Agent ID registry mismatch in '{c_name}' cohort definition."
            )

        # Relational foreign key verification for standard observations
        tx_ids_set = {t["txn_id"] for t in ds_data.get("transactions", [])}
        user_ids_set = {u["user_id"] for u in ds_data.get("users", [])}
        agent_ids_set = {a["agent_id"] for a in ds_data.get("agents", [])}
        for _, tobs in obs_data.get("transaction_observations", {}).items():
            if tobs.get("txn_id") not in tx_ids_set:
                raise ArtifactVerificationError(
                    f"Observation references unknown txn_id in cohort '{c_name}'"
                )
            if tobs.get("user_id") not in user_ids_set:
                raise ArtifactVerificationError(
                    f"Observation references unknown user_id in cohort '{c_name}'"
                )
            if tobs.get("agent_id") not in agent_ids_set:
                raise ArtifactVerificationError(
                    f"Observation references unknown agent_id in cohort '{c_name}'"
                )
        for uid in obs_data.get("user_observations", {}):
            if uid not in user_ids_set:
                raise ArtifactVerificationError(
                    f"User observation references unknown user_id in cohort '{c_name}'"
                )

        datasets[c_name] = ds_data
        observations[c_name] = obs_data
        splits_dict[c_name] = {"dataset": ds_data, "observations": obs_data}

    # 3. Disjointness and relational integrity check across standard cohorts
    try:
        assert_disjoint_splits({"splits": splits_dict, "manifest": manifest})
    except AssertionError as exc:
        raise ArtifactVerificationError(f"Split disjointness or integrity failed: {exc}") from exc

    # 4. Shifted test metadata and file validation
    try:
        shifted_meta = json.loads(shifted_meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ArtifactVerificationError(f"Failed to parse test_shifted.meta.json: {exc}") from exc

    if shifted_meta.get("schema_version") != 1:
        raise ArtifactVerificationError("Shifted test metadata schema_version must be 1")

    shifted_ds_file = s_dir / shifted_meta.get("file", "test_shifted.json")
    if not shifted_ds_file.is_file():
        raise ArtifactUnavailableError(f"Shifted test dataset file missing: {shifted_ds_file}")

    shifted_raw_bytes = shifted_ds_file.read_bytes()
    actual_shift_sha = hashlib.sha256(shifted_raw_bytes).hexdigest()
    if actual_shift_sha != shifted_meta.get("content_sha256"):
        try:
            parsed_shift_temp = json.loads(shifted_raw_bytes.decode("utf-8"))
            canon_shift_bytes = json.dumps(
                parsed_shift_temp, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            if hashlib.sha256(canon_shift_bytes).hexdigest() != shifted_meta.get("content_sha256"):
                raise ArtifactVerificationError(
                    f"Shifted test SHA-256 mismatch: meta={shifted_meta.get('content_sha256')}, "
                    f"actual={actual_shift_sha}"
                )
        except Exception as exc:
            raise ArtifactVerificationError(
                f"Shifted test SHA-256 mismatch: meta={shifted_meta.get('content_sha256')}, "
                f"actual={actual_shift_sha}"
            ) from exc

    shifted_obs_file = s_dir / shifted_meta.get(
        "observations_file", "test_shifted.observations.json"
    )
    if not shifted_obs_file.is_file():
        raise ArtifactUnavailableError(
            f"Shifted test observations file missing: {shifted_obs_file}"
        )

    shifted_obs_raw_bytes = shifted_obs_file.read_bytes()
    actual_shift_obs_sha = hashlib.sha256(shifted_obs_raw_bytes).hexdigest()
    if actual_shift_obs_sha != shifted_meta.get("observations_sha256"):
        try:
            parsed_so_temp = json.loads(shifted_obs_raw_bytes.decode("utf-8"))
            canon_so_bytes = json.dumps(
                parsed_so_temp, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            if hashlib.sha256(canon_so_bytes).hexdigest() != shifted_meta.get(
                "observations_sha256"
            ):
                raise ArtifactVerificationError("Shifted test observations SHA-256 mismatch")
        except Exception as exc:
            raise ArtifactVerificationError("Shifted test observations SHA-256 mismatch") from exc

    shifted_ds = json.loads(shifted_raw_bytes.decode("utf-8"))
    shifted_obs = json.loads(shifted_obs_raw_bytes.decode("utf-8"))

    # Shifted declared seed and counts validation
    shifted_declared_seed = shifted_meta.get("seed")
    if shifted_declared_seed is None or shifted_ds.get("seed") != shifted_declared_seed:
        raise ArtifactVerificationError(
            f"Shifted dataset seed ({shifted_ds.get('seed')}) mismatch with "
            f"declared seed ({shifted_declared_seed})"
        )
    if config is not None:
        cfg_test_seed = config.get("simulation", {}).get("seed_test")
        if cfg_test_seed is not None and shifted_declared_seed != cfg_test_seed:
            raise ArtifactVerificationError(
                f"Shifted test declared seed ({shifted_declared_seed}) does not match "
                f"configured seed_test ({cfg_test_seed})"
            )

    shift_counts = shifted_meta.get("counts", {})
    if len(shifted_ds.get("users", [])) != shift_counts.get("users"):
        raise ArtifactVerificationError(
            f"Shifted user count mismatch: declared {shift_counts.get('users')}, "
            f"actual {len(shifted_ds.get('users', []))}"
        )
    if len(shifted_ds.get("agents", [])) != shift_counts.get("agents"):
        raise ArtifactVerificationError(
            f"Shifted agent count mismatch: declared {shift_counts.get('agents')}, "
            f"actual {len(shifted_ds.get('agents', []))}"
        )
    if len(shifted_ds.get("transactions", [])) != shift_counts.get("transactions"):
        raise ArtifactVerificationError(
            f"Shifted transaction count mismatch: declared {shift_counts.get('transactions')}, "
            f"actual {len(shifted_ds.get('transactions', []))}"
        )
    if len(shifted_ds.get("sessions", [])) != shift_counts.get("sessions"):
        raise ArtifactVerificationError(
            f"Shifted session count mismatch: declared {shift_counts.get('sessions')}, "
            f"actual {len(shifted_ds.get('sessions', []))}"
        )

    # Verify shifted agent cohort matches canonical test cohort exactly and matches declared IDs
    shifted_agent_ids = sorted([a["agent_id"] for a in shifted_ds.get("agents", [])])
    test_agent_ids = sorted(cohorts["test"].get("agent_ids", []))
    if shifted_agent_ids != test_agent_ids:
        raise ArtifactVerificationError(
            "Distribution-shifted test agents do not match canonical test agent cohort."
        )
    if shifted_agent_ids != sorted(shifted_meta.get("agent_ids", [])):
        raise ArtifactVerificationError(
            "Shifted dataset agent IDs do not match declared agent_ids in metadata"
        )

    # Shifted observation foreign key relational integrity
    shift_tx_ids = {t["txn_id"] for t in shifted_ds.get("transactions", [])}
    shift_u_ids = {u["user_id"] for u in shifted_ds.get("users", [])}
    shift_a_ids = {a["agent_id"] for a in shifted_ds.get("agents", [])}
    for _, sobs in shifted_obs.get("transaction_observations", {}).items():
        if sobs.get("txn_id") not in shift_tx_ids:
            raise ArtifactVerificationError("Shifted observation references unknown txn_id")
        if sobs.get("user_id") not in shift_u_ids:
            raise ArtifactVerificationError("Shifted observation references unknown user_id")
        if sobs.get("agent_id") not in shift_a_ids:
            raise ArtifactVerificationError("Shifted observation references unknown agent_id")
    for uid in shifted_obs.get("user_observations", {}):
        if uid not in shift_u_ids:
            raise ArtifactVerificationError("Shifted user observation references unknown user_id")

    # Verify shifted agents and users are completely disjoint from train and validation
    train_agents = set(cohorts["train"].get("agent_ids", []))
    val_agents = set(cohorts["validation"].get("agent_ids", []))
    train_users = {u["user_id"] for u in datasets["train"]["users"]}
    val_users = {u["user_id"] for u in datasets["validation"]["users"]}
    shift_users = {u["user_id"] for u in shifted_ds.get("users", [])}

    if set(shifted_agent_ids) & train_agents:
        raise ArtifactVerificationError("Shifted test agents overlap with train agents.")
    if set(shifted_agent_ids) & val_agents:
        raise ArtifactVerificationError("Shifted test agents overlap with validation agents.")
    if shift_users & train_users:
        raise ArtifactVerificationError("Shifted test users overlap with train users.")
    if shift_users & val_users:
        raise ArtifactVerificationError("Shifted test users overlap with validation users.")

    # Validate shifted dataset schema
    try:
        validate_dataset(shifted_ds)
    except Exception as exc:
        raise ArtifactVerificationError(f"Shifted test dataset failed schema validation: {exc}")

    return {
        "manifest": manifest,
        "shifted_meta": shifted_meta,
        "datasets": datasets,
        "observations": observations,
        "shifted_dataset": shifted_ds,
        "shifted_observations": shifted_obs,
    }


def _validate_header(value: Any, artifact_type: str) -> None:
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise ArtifactVerificationError("Invalid manifest schema")
    if value["schema_version"] != 1 or value.get("synthetic") is not True:
        raise ArtifactVerificationError("Unsupported schema or non-synthetic artifact")
    if value.get("artifact_type") != artifact_type:
        raise ArtifactVerificationError("Invalid artifact_type")
    if not isinstance(value.get("config_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["config_sha256"]
    ):
        raise ArtifactVerificationError("Invalid config SHA-256 provenance")


def _validate_model_manifest(value: Any, kind: str) -> None:
    if not isinstance(value, dict):
        raise ArtifactVerificationError("Model manifest must be an object")
    artifact_type = value.get("artifact_type")
    if artifact_type not in ("sathi_evaluation_run", "sathi_deployment_bundle"):
        raise ArtifactVerificationError("Invalid model manifest artifact_type")
    _validate_header(value, artifact_type)
    features = value.get("features", {}).get(kind)
    if not isinstance(features, list) or len(features) != len(set(features)):
        raise ArtifactVerificationError("Invalid declared feature schema")
    assert_feature_columns(features)


def _finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate_snapshot(snapshot: Any, manifest: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise ArtifactVerificationError("Invalid snapshot schema")
    if snapshot.get("synthetic") is not True or snapshot.get("snapshot_type") != (
        "curated_synthetic_inference_snapshot"
    ):
        raise ArtifactVerificationError("Invalid synthetic snapshot type")
    for field in ("as_of", "cutoff", "window_days"):
        if snapshot.get(field) != manifest["feature_provenance"].get(field):
            raise ArtifactVerificationError("Snapshot window provenance mismatch")
    schemas = (
        (
            "customers",
            "assisted_classifier",
            "user_id",
            "predicted_probability",
            {"user_id", "features", "predicted_probability", "predicted_class", "explanations"},
        ),
        (
            "agents",
            "agent_anomaly",
            "agent_id",
            "risk_score",
            {"agent_id", "features", "risk_score", "risk_level", "reasons"},
        ),
    )
    for rows_key, kind, id_key, score_key, allowed in schemas:
        declared = manifest["features"].get(kind)
        if not isinstance(declared, list) or len(set(declared)) != len(declared):
            raise ArtifactVerificationError("Invalid snapshot feature schema")
        assert_feature_columns(declared)
        rows = snapshot.get(rows_key)
        if not isinstance(rows, list):
            raise ArtifactVerificationError("Missing snapshot subject list")
        ids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - allowed:
                raise ArtifactVerificationError("Unexpected snapshot fields")
            identifier = row.get(id_key)
            if not isinstance(identifier, str) or not identifier or identifier in ids:
                raise ArtifactVerificationError("Missing or duplicate synthetic ID")
            ids.add(identifier)
            features = row.get("features")
            # JSON object key order is irrelevant; the declared list fixes model input order.
            if not isinstance(features, dict) or set(features) != set(declared):
                raise ArtifactVerificationError("Snapshot feature schema mismatch")
            if not all(_finite_number(value) for value in features.values()):
                raise ArtifactVerificationError("Non-finite snapshot features")
            score = row.get(score_key)
            if not _finite_number(score) or not 0 <= score <= 1:
                raise ArtifactVerificationError("Invalid prediction range")
            if kind == "assisted_classifier" and (
                type(row.get("predicted_class")) is not int or row["predicted_class"] not in (0, 1)
            ):
                raise ArtifactVerificationError("Invalid predicted class")


class ArtifactLoader:
    """Secure artifact loader that verifies checksums, schema, and trained feature columns."""

    @staticmethod
    def load_assisted_model(
        artifact_path: str | Path,
        manifest_path: str | Path | None = None,
    ) -> AssistedUserClassifier:
        """Load and verify serialized AssistedUserClassifier joblib artifact.

        Fails closed BEFORE deserialization on:
        - Missing artifact file or missing manifest.
        - Absent or mismatched SHA-256 checksum in manifest.
        - Unsupported schema_version, missing synthetic flag, or invalid artifact_type.
        - Missing declared feature schema or config provenance in manifest.

        Validates after deserialization:
        - Exact fitted feature order matches declared features in manifest.
        - All feature names belong to feature guard allowlist.
        """
        path = Path(artifact_path)
        if not path.is_file():
            raise ArtifactUnavailableError(f"Assisted classifier artifact not found: {path}")

        m_path = Path(manifest_path) if manifest_path is not None else path.parent / "manifest.json"
        if not m_path.is_file():
            raise ArtifactUnavailableError(
                f"Missing manifest file for assisted model verification: {m_path}"
            )

        try:
            m_data = json.loads(m_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ArtifactVerificationError(f"Failed to read manifest for verification: {exc}")

        _validate_model_manifest(m_data, "assisted_classifier")
        if m_data.get("schema_version") != 1:
            raise ArtifactVerificationError(
                f"Unsupported manifest schema_version: {m_data.get('schema_version')}"
            )
        if m_data.get("synthetic") is not True:
            raise ArtifactVerificationError("Manifest must declare synthetic=true")

        expected_sha = None
        if "model_artifacts" in m_data and "assisted_sha256" in m_data["model_artifacts"]:
            expected_sha = m_data["model_artifacts"]["assisted_sha256"]
        elif "files" in m_data and path.name in m_data["files"]:
            expected_sha = m_data["files"][path.name].get("sha256")

        if not expected_sha:
            raise ArtifactVerificationError(f"Absent SHA-256 checksum for {path.name} in manifest")

        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ArtifactVerificationError(
                f"Assisted model SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
            )

        declared_features = m_data.get("features", {}).get("assisted_classifier") or m_data.get(
            "feature_schema", {}
        ).get("assisted_classifier")
        if not declared_features:
            raise ArtifactVerificationError(
                "Missing declared feature schema provenance for assisted classifier in manifest"
            )
        if "config_sha256" not in m_data and "feature_provenance" not in m_data:
            raise ArtifactVerificationError("Missing config or feature provenance in manifest")

        from app.models.assisted_model import AssistedUserClassifier

        try:
            clf = AssistedUserClassifier.load(path)
        except Exception as exc:
            raise ArtifactVerificationError(f"Failed to deserialize assisted model: {exc}") from exc

        if not clf.feature_names_:
            raise ArtifactVerificationError("Loaded assisted model has empty feature_names_")

        if list(clf.feature_names_) != list(declared_features):
            raise ArtifactVerificationError(
                f"Trained feature order does not match declared features in manifest: "
                f"expected {declared_features}, got {clf.feature_names_}"
            )
        assert_feature_columns(clf.feature_names_)

        return clf

    @staticmethod
    def load_agent_model(
        artifact_path: str | Path,
        manifest_path: str | Path | None = None,
    ) -> AgentAnomalyDetector:
        """Load and verify serialized AgentAnomalyDetector joblib artifact."""
        path = Path(artifact_path)
        if not path.is_file():
            raise ArtifactUnavailableError(f"Agent detector artifact not found: {path}")

        m_path = Path(manifest_path) if manifest_path is not None else path.parent / "manifest.json"
        if not m_path.is_file():
            raise ArtifactUnavailableError(
                f"Missing manifest file for agent model verification: {m_path}"
            )

        try:
            m_data = json.loads(m_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ArtifactVerificationError(f"Failed to read manifest for verification: {exc}")

        _validate_model_manifest(m_data, "agent_anomaly")
        if m_data.get("schema_version") != 1:
            raise ArtifactVerificationError(
                f"Unsupported manifest schema_version: {m_data.get('schema_version')}"
            )
        if m_data.get("synthetic") is not True:
            raise ArtifactVerificationError("Manifest must declare synthetic=true")

        expected_sha = None
        if "model_artifacts" in m_data and "agent_sha256" in m_data["model_artifacts"]:
            expected_sha = m_data["model_artifacts"]["agent_sha256"]
        elif "files" in m_data and path.name in m_data["files"]:
            expected_sha = m_data["files"][path.name].get("sha256")

        if not expected_sha:
            raise ArtifactVerificationError(f"Absent SHA-256 checksum for {path.name} in manifest")

        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ArtifactVerificationError(
                f"Agent detector SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
            )

        declared_features = m_data.get("features", {}).get("agent_anomaly") or m_data.get(
            "feature_schema", {}
        ).get("agent_anomaly")
        if not declared_features:
            raise ArtifactVerificationError(
                "Missing declared feature schema provenance for agent anomaly in manifest"
            )
        if "config_sha256" not in m_data and "feature_provenance" not in m_data:
            raise ArtifactVerificationError("Missing config or feature provenance in manifest")

        from app.models.agent_model import AgentAnomalyDetector

        try:
            detector = AgentAnomalyDetector.load(path)
        except Exception as exc:
            raise ArtifactVerificationError(f"Failed to deserialize agent detector: {exc}") from exc

        if not detector.feature_names_:
            raise ArtifactVerificationError("Loaded agent detector has empty feature_names_")

        if list(detector.feature_names_) != list(declared_features):
            raise ArtifactVerificationError(
                f"Trained feature order does not match declared features in manifest: "
                f"expected {declared_features}, got {detector.feature_names_}"
            )
        assert_feature_columns(detector.feature_names_)

        return detector

    @staticmethod
    def load_deployment_bundle(
        deployment_dir: str | Path,
        load_models: bool = True,
    ) -> dict[str, Any]:
        """Verify and load curated deployment inference bundle.

        If load_models=False, verifies all bundle files, provenance, and snapshots
        without importing joblib or deserializing models.
        """
        b_dir = Path(deployment_dir)
        if not b_dir.is_dir():
            raise ArtifactUnavailableError(f"Deployment directory not found: {b_dir}")

        manifest_path = b_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ArtifactUnavailableError(f"Deployment manifest not found: {manifest_path}")

        m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_header(m_data, "sathi_deployment_bundle")
        if m_data.get("schema_version") != 1:
            raise ArtifactVerificationError(
                f"Deployment manifest unsupported schema_version: {m_data.get('schema_version')}"
            )
        if m_data.get("synthetic") is not True:
            raise ArtifactVerificationError("Deployment manifest must declare synthetic=true")
        if m_data.get("artifact_type") != "sathi_deployment_bundle":
            raise ArtifactVerificationError(
                f"Invalid bundle artifact_type: {m_data.get('artifact_type')}"
            )

        expected_files = {
            "assisted.joblib",
            "agent.joblib",
            "metrics_provenance.json",
            "synthetic_inference_snapshot.json",
            "results.json",
        }
        files_dict = m_data.get("files", {})
        missing_expected = expected_files - set(files_dict.keys())
        if missing_expected:
            raise ArtifactVerificationError(
                f"Deployment bundle manifest missing expected files: {sorted(missing_expected)}"
            )

        for fname, finfo in files_dict.items():
            if (
                Path(fname).is_absolute()
                or "/" in fname
                or "\\" in fname
                or ".." in fname
                or fname.startswith("/")
                or fname.startswith("\\")
            ):
                raise ArtifactVerificationError(
                    f"Path escape or absolute path detected in bundle manifest: {fname}"
                )
            fpath = b_dir / fname
            if not fpath.is_file():
                raise ArtifactUnavailableError(f"Required bundle file missing: {fname}")
            fbytes = fpath.read_bytes()
            if len(fbytes) != finfo.get("size_bytes"):
                raise ArtifactVerificationError(
                    f"Bundle file '{fname}' size mismatch: expected {finfo.get('size_bytes')}, "
                    f"got {len(fbytes)}"
                )
            actual_hash = hashlib.sha256(fbytes).hexdigest()
            if actual_hash != finfo["sha256"]:
                raise ArtifactVerificationError(
                    f"Deployment bundle file '{fname}' hash mismatch: "
                    f"expected {finfo['sha256']}, got {actual_hash}"
                )

        for req_field in ("config_sha256", "features", "seeds", "cohorts"):
            if req_field not in m_data:
                raise ArtifactVerificationError(
                    f"Deployment bundle manifest missing required provenance field '{req_field}'"
                )

        metrics_provenance = json.loads(
            (b_dir / "metrics_provenance.json").read_text(encoding="utf-8")
        )
        snapshot = json.loads(
            (b_dir / "synthetic_inference_snapshot.json").read_text(encoding="utf-8")
        )
        results = json.loads((b_dir / "results.json").read_text(encoding="utf-8"))

        _validate_snapshot(snapshot, m_data)
        if results.get("schema_version") != 1 or results.get("synthetic") is not True:
            raise ArtifactVerificationError("Invalid result schema or provenance")
        if metrics_provenance.get("schema_version") != 1 or (
            metrics_provenance.get("synthetic") is not True
        ):
            raise ArtifactVerificationError("Invalid metrics schema or provenance")
        if metrics_provenance.get("results") != results:
            raise ArtifactVerificationError("Embedded results differ from results artifact")
        for field in ("config_sha256", "git_revision", "final_run_timestamp"):
            if metrics_provenance.get(field) != m_data.get(field):
                raise ArtifactVerificationError("Metrics provenance mismatch")
        for field in ("as_of", "cutoff", "window_days"):
            if metrics_provenance.get(field) != snapshot.get(field):
                raise ArtifactVerificationError("Metrics/snapshot window mismatch")
        if results.get("final_run_timestamp") != m_data.get("final_run_timestamp"):
            raise ArtifactVerificationError("Result run timestamp mismatch")

        assisted_model = None
        agent_model = None
        if load_models:
            assisted_model = ArtifactLoader.load_assisted_model(
                b_dir / "assisted.joblib", manifest_path=manifest_path
            )
            agent_model = ArtifactLoader.load_agent_model(
                b_dir / "agent.joblib", manifest_path=manifest_path
            )

        return {
            "assisted_model": assisted_model,
            "agent_model": agent_model,
            "metrics_provenance": metrics_provenance,
            "synthetic_inference_snapshot": snapshot,
            "results": results,
            "manifest": m_data,
        }

    @staticmethod
    def load_deployment_bundle_json(deployment_dir: str | Path) -> dict[str, Any]:
        """JSON-only verified deployment bundle loader without importing joblib or models."""
        return ArtifactLoader.load_deployment_bundle(deployment_dir, load_models=False)


def export_deployment_bundle(
    output_dir: Path | str,
    assisted_clf: AssistedUserClassifier,
    agent_detector: AgentAnomalyDetector,
    results: dict[str, Any],
    manifest: dict[str, Any],
    sample_customers: list[dict[str, Any]],
    sample_agents: list[dict[str, Any]],
    as_of: str,
    window_days: int,
    cutoff: str,
) -> Path:
    """Export small curated deployment bundle for serving and frontend inspection.

    Curated bundle contains:
    - Serialized assisted and agent models.
    - Summary metrics and provenance metadata JSON.
    - Full evaluation results JSON for frontend consumption.
    - Bounded synthetic inference snapshot (numeric features + predictions + SHAP explanations),
      strictly omitting ground-truth labels and demographics.
    - Deployment manifest with cryptographic hashes of all bundle files and provenance.
    """
    deploy_dir = Path(output_dir) / "deployment"
    deploy_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save model artifacts
    assisted_path = deploy_dir / "assisted.joblib"
    agent_path = deploy_dir / "agent.joblib"
    assisted_clf.save(assisted_path)
    agent_detector.save(agent_path)

    # 2. Results JSON for UI
    results_bytes = json.dumps(results, sort_keys=True, indent=2).encode("utf-8")
    (deploy_dir / "results.json").write_bytes(results_bytes)

    # 3. Metrics and provenance JSON
    exp1 = results.get("experiment_1_assisted_detection", {})
    exp2 = results.get("experiment_2_agent_anomaly", {})
    fairness = results.get("fairness_evaluation", {}).get("held_out_canonical", {})

    held_out_clf = exp1.get("held_out_test", {}).get("assisted_classifier", {})
    pr_auc = held_out_clf.get("pr_auc")
    rec_80 = held_out_clf.get("recall_at_80p_precision")
    brier = held_out_clf.get("brier_score")

    comb_m = exp2.get("combined_ensemble", {})

    metrics_provenance = {
        "schema_version": 1,
        "synthetic": True,
        "description": (
            "Sathi deployment inference bundle. Models trained on synthetic 90-day simulation "
            f"with {window_days}-day offline behavioral window. "
            "Zero demographic or ground-truth features."
        ),
        "as_of": as_of,
        "cutoff": cutoff,
        "window_days": window_days,
        "final_run_timestamp": manifest.get("final_run_timestamp"),
        "git_revision": manifest.get("git_revision", "unknown"),
        "config_sha256": manifest["config_sha256"],
        "key_metrics": {
            "assisted_classifier": {
                "pr_auc": pr_auc,
                "recall_at_80p_precision": rec_80,
                "brier_score": brier,
                "classification_threshold": assisted_clf.classification_threshold,
            },
            "agent_anomaly": {
                "precision_at_k": comb_m.get("precision_at_k"),
                "recall_on_skimmers": comb_m.get("recall_on_skimmers"),
                "false_flag_rate_honest_high_volume": comb_m.get(
                    "false_flag_rate_honest_high_volume"
                ),
                "review_top_k": agent_detector.review_top_k,
                "high_risk_threshold": agent_detector.high_risk_threshold,
                "medium_risk_threshold": agent_detector.medium_risk_threshold,
            },
            "fairness": {
                "target_max_tpr_gap": fairness.get("target_max_tpr_gap"),
                "observed_max_tpr_gap": fairness.get("global_max_tpr_gap"),
                "satisfies_target": fairness.get("satisfies_fairness_target"),
            },
        },
        "results": results,
    }
    met_bytes = json.dumps(metrics_provenance, sort_keys=True, indent=2).encode("utf-8")
    (deploy_dir / "metrics_provenance.json").write_bytes(met_bytes)

    # 4. Curated synthetic inference snapshot (bounded subjects, NO labels, NO demographics)
    snapshot = {
        "schema_version": 1,
        "synthetic": True,
        "snapshot_type": "curated_synthetic_inference_snapshot",
        "selection": "Top predicted probability/risk, stable ID ties; no truth labels",
        "disclaimer": (
            "Synthetic simulation snapshot for offline demo and verification; "
            "never present artifact subjects as live customer records or runtime demo ledger."
        ),
        "as_of": as_of,
        "cutoff": cutoff,
        "window_days": window_days,
        "customers": sample_customers,
        "agents": sample_agents,
    }
    snap_bytes = json.dumps(snapshot, sort_keys=True, indent=2).encode("utf-8")
    (deploy_dir / "synthetic_inference_snapshot.json").write_bytes(snap_bytes)

    # 5. Generate deployment bundle manifest with all required files
    files_manifest: dict[str, Any] = {}
    for fname in (
        "assisted.joblib",
        "agent.joblib",
        "metrics_provenance.json",
        "synthetic_inference_snapshot.json",
        "results.json",
    ):
        fpath = deploy_dir / fname
        fbytes = fpath.read_bytes()
        files_manifest[fname] = {
            "size_bytes": len(fbytes),
            "sha256": hashlib.sha256(fbytes).hexdigest(),
        }

    dep_manifest = {
        "schema_version": 1,
        "synthetic": True,
        "artifact_type": "sathi_deployment_bundle",
        "final_run_timestamp": manifest.get("final_run_timestamp"),
        "git_revision": manifest.get("git_revision", "unknown"),
        "config_sha256": manifest.get("config_sha256"),
        "features": manifest.get("features", {}),
        "seeds": manifest.get("seeds", {}),
        "cohorts": manifest.get("cohorts", {}),
        "feature_provenance": manifest.get("feature_provenance", {}),
        "files": files_manifest,
    }
    dep_bytes = json.dumps(dep_manifest, sort_keys=True, indent=2).encode("utf-8")
    (deploy_dir / "manifest.json").write_bytes(dep_bytes)

    return deploy_dir
