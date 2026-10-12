"""P2-08: keep level_engine boundary coverage at 20+ collected cases."""
from __future__ import annotations

import ast
from pathlib import Path

MIN_LEVEL_ENGINE_CASES = 20
LEVEL_ENGINE_TEST_PATH = Path(__file__).with_name("test_level_engine.py")


def test_level_engine_boundary_case_count_is_at_least_20():
    case_count = _count_pytest_cases(LEVEL_ENGINE_TEST_PATH)

    assert case_count >= MIN_LEVEL_ENGINE_CASES


def _count_pytest_cases(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = 0
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        param_count = _parametrize_case_count(node)
        total += param_count if param_count is not None else 1
    return total


def _parametrize_case_count(node: ast.FunctionDef) -> int | None:
    counts: list[int] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if not _is_pytest_parametrize(decorator.func):
            continue
        if len(decorator.args) < 2:
            continue
        values = decorator.args[1]
        if isinstance(values, (ast.List, ast.Tuple)):
            counts.append(len(values.elts))
    if not counts:
        return None
    product = 1
    for count in counts:
        product *= count
    return product


def _is_pytest_parametrize(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "parametrize"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    )
