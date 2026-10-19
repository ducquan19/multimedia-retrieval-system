"""Dependency rules between the backend packages, checked on every test run.

Inner layers must not depend on outer ones: the adapters (repositories, infrastructure) and the
domain models know nothing about the HTTP API, and the services do not reach into routers.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

# package -> top-level packages it must not import
FORBIDDEN = {
    "models": {"core", "schemas", "services", "repositories", "infrastructure", "router"},
    "repositories": {"schemas", "services", "router", "factories"},
    "infrastructure": {"schemas", "services", "repositories", "router", "factories"},
    "schemas": {"services", "repositories", "infrastructure", "router", "factories"},
    "services": {"router", "factories"},
}
# The parts of core the inner layers may use: plain policies and constants, not the wiring.
ALLOWED_CORE = {"core.constants", "core.intro_exclusion", "core.timing"}


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def violations(package: str) -> list[str]:
    found = []
    for path in sorted((SRC / package).rglob("*.py")):
        for module in imported_modules(path):
            top = module.split(".")[0]
            if top == "core" and package in {"repositories", "infrastructure"}:
                if module not in ALLOWED_CORE:
                    found.append(f"{path.relative_to(SRC)} imports {module}")
            elif top in FORBIDDEN[package]:
                found.append(f"{path.relative_to(SRC)} imports {module}")
    return found


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_layer_dependencies(package: str) -> None:
    assert violations(package) == []
