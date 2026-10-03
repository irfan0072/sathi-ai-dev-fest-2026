"""Lightweight artifact exports; offline evaluation is imported only on demand."""

from typing import Any

from app.evaluation.artifacts import (
    ArtifactError,
    ArtifactLoader,
    ArtifactUnavailableError,
    ArtifactVerificationError,
    SanityCeilingExceededError,
    export_deployment_bundle,
    validate_manifest_and_metadata,
)

__all__ = [
    "ArtifactError",
    "ArtifactLoader",
    "ArtifactUnavailableError",
    "ArtifactVerificationError",
    "EvaluationRunner",
    "SanityCeilingExceededError",
    "export_deployment_bundle",
    "validate_manifest_and_metadata",
]


def __getattr__(name: str) -> Any:
    if name == "EvaluationRunner":
        from app.evaluation.suite import EvaluationRunner

        return EvaluationRunner
    raise AttributeError(name)
