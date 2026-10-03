"""Tiny saved-output fixture; never trains or reads final evaluation cohorts."""

import hashlib
import json
from pathlib import Path

from app.data.config import load_config


def write_test_bundle(directory: Path) -> Path:
    directory.mkdir()
    config_hash = hashlib.sha256(
        json.dumps(load_config(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    window = {
        "as_of": "2026-12-30T00:00:00+00:00",
        "cutoff": "2026-11-30T00:00:00+00:00",
        "window_days": 30,
    }
    stamp = "2026-10-03T00:00:00+00:00"
    revision = "0" * 40
    results = {
        "schema_version": 1,
        "synthetic": True,
        "final_run_timestamp": stamp,
        "test_fixture": "stored numerical outputs, not measured model performance",
    }
    snapshot = {
        "schema_version": 1,
        "synthetic": True,
        "snapshot_type": "curated_synthetic_inference_snapshot",
        **window,
        "selection": "test fixture",
        "customers": [
            {
                "user_id": "U_fixture_1",
                "features": {"top_agent_share": 0.7},
                "predicted_probability": 0.73,
                "predicted_class": 1,
                "explanations": [
                    {
                        "feature": "top_agent_share",
                        "value": 0.7,
                        "attribution": 0.4,
                        "attribution_unit": "log_odds",
                    }
                ],
            }
        ],
        "agents": [
            {
                "agent_id": "A_fixture_1",
                "features": {"agent_fee_ratio_over_official": 1.15},
                "risk_score": 0.82,
                "risk_level": "HIGH",
                "reasons": [
                    {"feature": "fee_ratio_vs_official", "value": 1.15, "peer_median": 1.0}
                ],
            }
        ],
    }
    meta = {
        "schema_version": 1,
        "synthetic": True,
        "config_sha256": config_hash,
        "git_revision": revision,
        "final_run_timestamp": stamp,
        **window,
        "results": results,
    }
    for name, value in (
        ("results.json", results),
        ("metrics_provenance.json", meta),
        ("synthetic_inference_snapshot.json", snapshot),
    ):
        (directory / name).write_text(json.dumps(value))
    for name in ("assisted.joblib", "agent.joblib"):
        (directory / name).write_bytes(b"Not a serialized model; JSON-only paths must not load it")
    manifest = {
        "schema_version": 1,
        "synthetic": True,
        "artifact_type": "sathi_deployment_bundle",
        "config_sha256": config_hash,
        "git_revision": revision,
        "final_run_timestamp": stamp,
        "feature_provenance": window,
        "seeds": {"train": 42},
        "cohorts": {},
        "features": {
            "assisted_classifier": ["top_agent_share"],
            "agent_anomaly": ["agent_fee_ratio_over_official"],
        },
        "files": {
            path.name: {
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in directory.iterdir()
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory
