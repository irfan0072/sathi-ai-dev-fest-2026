"""Tests for repository structure checker (scripts/check_structure.py)."""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts directory to sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_structure  # noqa: E402


def test_check_paths_clean() -> None:
    """Verify that all required repository paths exist."""
    errors = check_structure.check_paths()
    assert errors == [], f"Unexpected path errors: {errors}"


def test_check_pyproject_clean() -> None:
    """Verify backend/pyproject.toml satisfies structure requirements."""
    errors = check_structure.check_pyproject()
    assert errors == [], f"Unexpected pyproject errors: {errors}"


def test_check_package_json_clean() -> None:
    """Verify frontend/package.json satisfies structure requirements."""
    errors = check_structure.check_package_json()
    assert errors == [], f"Unexpected package.json errors: {errors}"


def test_main_returns_zero() -> None:
    """Verify main() entrypoint passes with returncode 0."""
    assert check_structure.main() == 0
