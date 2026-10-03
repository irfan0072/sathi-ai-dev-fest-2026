"""Hash-verified loading of offline intelligence artifacts. No model runs at request time."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ARTIFACT_NAMES = ("liquidity", "uplift")


class IntelligenceArtifactError(RuntimeError):
    pass


def artifact_dir() -> Path:
    return Path(os.getenv("SATHI_INTELLIGENCE_DIR", "data/artifacts/intelligence"))


def write_artifacts(directory: Path, artifacts: dict[str, Any], provenance: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, payload in artifacts.items():
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        (directory / f"{name}.json").write_text(body, encoding="utf-8")
        hashes[name] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    manifest = {"artifacts": hashes, **provenance}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                             encoding="utf-8")


def load_artifact(name: str, directory: Path | None = None) -> dict[str, Any]:
    if name not in ARTIFACT_NAMES:
        raise IntelligenceArtifactError("Unknown artifact")
    directory = directory or artifact_dir()
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        raw = (directory / f"{name}.json").read_bytes()
    except (OSError, ValueError) as exc:
        raise IntelligenceArtifactError("Intelligence artifact unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != manifest.get("artifacts", {}).get(name):
        raise IntelligenceArtifactError("Intelligence artifact hash mismatch")
    payload = json.loads(raw)
    payload["provenance"] = {k: v for k, v in manifest.items() if k != "artifacts"}
    return payload
