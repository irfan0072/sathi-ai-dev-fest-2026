#!/usr/bin/env python3
"""Tooling script to verify empty component structure and dependency manifests."""

import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_PATHS = [
    REPO_ROOT / "backend" / "pyproject.toml",
    REPO_ROOT / "backend" / "app" / "__init__.py",
    REPO_ROOT / "backend" / "app" / "features" / "__init__.py",
    REPO_ROOT / "backend" / "app" / "models" / "__init__.py",
    REPO_ROOT / "backend" / "app" / "policy" / "__init__.py",
    REPO_ROOT / "backend" / "app" / "mandates" / "__init__.py",
    REPO_ROOT / "backend" / "app" / "verification" / "__init__.py",
    REPO_ROOT / "backend" / "app" / "copilot" / "__init__.py",
    REPO_ROOT / "backend" / "tests" / ".gitkeep",
    REPO_ROOT / "frontend" / "package.json",
    REPO_ROOT / "frontend" / "src" / ".gitkeep",
    REPO_ROOT / "Makefile",
    REPO_ROOT / "scripts" / "check_structure.py",
]


def check_paths() -> list[str]:
    errors = []
    for path in REQUIRED_PATHS:
        if not path.exists():
            errors.append(f"Missing required path: {path.relative_to(REPO_ROOT)}")
    return errors


def check_pyproject() -> list[str]:
    errors = []
    pyproject_path = REPO_ROOT / "backend" / "pyproject.toml"
    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        return [f"Failed to parse backend/pyproject.toml: {e}"]

    project = data.get("project", {})
    req_python = project.get("requires-python", "")
    if ">=3.11" not in req_python:
        errors.append(
            f"backend/pyproject.toml requires-python must include '>=3.11', got '{req_python}'"
        )

    deps = project.get("dependencies", [])
    dep_names = [d.split(">=")[0].split("[")[0].strip() for d in deps]
    for required_dep in ("fastapi", "uvicorn"):
        if required_dep not in dep_names:
            errors.append(f"backend/pyproject.toml missing required dependency: {required_dep}")

    dev_deps = project.get("optional-dependencies", {}).get("dev", [])
    dev_names = [d.split(">=")[0].split("[")[0].strip() for d in dev_deps]
    for required_dev in ("pytest", "httpx", "ruff"):
        if required_dev not in dev_names:
            errors.append(f"backend/pyproject.toml missing dev dependency: {required_dev}")

    tool = data.get("tool", {})
    if "setuptools" not in tool or "packages" not in tool["setuptools"]:
        errors.append("backend/pyproject.toml missing setuptools package discovery configuration")

    if "pytest" not in tool:
        errors.append("backend/pyproject.toml missing tool.pytest configuration")

    if "ruff" not in tool:
        errors.append("backend/pyproject.toml missing tool.ruff configuration")

    return errors


def check_package_json() -> list[str]:
    errors = []
    package_json_path = REPO_ROOT / "frontend" / "package.json"
    try:
        with open(package_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return [f"Failed to parse frontend/package.json: {e}"]

    node_engine = data.get("engines", {}).get("node", "")
    minimum_majors = [int(value) for value in re.findall(r"(?:\^|>=)\s*(\d+)", node_engine)]
    if not minimum_majors or min(minimum_majors) < 20:
        errors.append(
            f"frontend/package.json engines.node must require Node 20 or newer, got '{node_engine}'"
        )

    deps = data.get("dependencies", {})
    for required_dep in ("react", "react-dom"):
        if required_dep not in deps:
            errors.append(f"frontend/package.json missing dependency: {required_dep}")

    dev_deps = data.get("devDependencies", {})
    for required_dev in ("vite", "vitest", "eslint"):
        if required_dev not in dev_deps:
            errors.append(f"frontend/package.json missing devDependency: {required_dev}")

    return errors


def main() -> int:
    all_errors = []
    all_errors.extend(check_paths())
    all_errors.extend(check_pyproject())
    all_errors.extend(check_package_json())

    if all_errors:
        print("FAIL: Component structure and manifest validation failed:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("PASS: Component structure and dependency manifests verified successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
