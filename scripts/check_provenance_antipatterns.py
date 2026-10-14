#!/usr/bin/env python3
"""Check changed provenance decisions for two known unsafe patterns."""

import ast
import re
import subprocess
import sys
from pathlib import Path

_DECISION_NAME = re.compile(r"reuse|provenance|lineage", re.IGNORECASE)


def _is_id_access(node: ast.AST, variable: str) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == variable
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in {"id", "artifact_id"}
    )


def _uses_id(node: ast.AST, variable: str) -> bool:
    return any(
        _is_id_access(child, variable)
        or (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "getattr"
            and len(child.args) > 1
            and isinstance(child.args[0], ast.Name)
            and child.args[0].id == variable
            and isinstance(child.args[1], ast.Constant)
            and child.args[1].value in {"id", "artifact_id"}
        )
        for child in ast.walk(node)
    )


def _filtered_dict_member(node: ast.AST, variable: str) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "isinstance"
        and len(child.args) > 1
        and isinstance(child.args[0], ast.Name)
        and child.args[0].id == variable
        and (
            (isinstance(child.args[1], ast.Name) and child.args[1].id == "dict")
            or (
                isinstance(child.args[1], ast.Tuple)
                and any(isinstance(item, ast.Name) and item.id == "dict" for item in child.args[1].elts)
            )
        )
        for child in ast.walk(node)
    )


def _unique_guard_line(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> int | None:
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.NotEq):
            continue
        left, right = node.left, node.comparators[0]
        for length, unique in ((left, right), (right, left)):
            if (
                isinstance(length, ast.Call)
                and isinstance(length.func, ast.Name)
                and length.func.id == "len"
                and len(length.args) == 1
                and isinstance(length.args[0], ast.Name)
                and length.args[0].id == name
                and isinstance(unique, ast.Call)
                and isinstance(unique.func, ast.Name)
                and unique.func.id == "len"
                and len(unique.args) == 1
                and isinstance(unique.args[0], ast.Call)
                and isinstance(unique.args[0].func, ast.Name)
                and unique.args[0].func.id == "set"
                and len(unique.args[0].args) == 1
                and isinstance(unique.args[0].args[0], ast.Name)
                and unique.args[0].args[0].id == name
            ):
                return node.lineno
    return None


def inspect_source(source: str, filename: str = "<source>") -> list[str]:
    """Return findings as ``filename:line:rule`` without executing source."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []

    findings: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        comprehensions = [
            node for node in ast.walk(function)
            if isinstance(node, (ast.ListComp, ast.GeneratorExp))
        ]
        for comp in comprehensions:
            if not comp.generators or not isinstance(comp.generators[0].target, ast.Name):
                continue
            variable = comp.generators[0].target.id
            if any(
                _filtered_dict_member(predicate, variable)
                for generator in comp.generators
                for predicate in generator.ifs
            ):
                findings.append(f"{filename}:{comp.lineno}:malformed-member filtering")

        # An ID-list comprehension is safe only as the input to a uniqueness
        # guard that runs before any later identity-based selection.
        for comp in comprehensions:
            if not comp.generators or not isinstance(comp.generators[0].target, ast.Name):
                continue
            variable = comp.generators[0].target.id
            if not _uses_id(comp.elt, variable) and not any(
                _uses_id(predicate, variable)
                for generator in comp.generators
                for predicate in generator.ifs
            ):
                continue

            parent_assignment = next(
                (
                    node for node in ast.walk(function)
                    if isinstance(node, ast.Assign)
                    and node.value is comp
                    and any(isinstance(target, ast.Name) and target.id == "ids" for target in node.targets)
                ),
                None,
            )
            if parent_assignment is not None:
                guard = _unique_guard_line(function, "ids")
                later_selection = min(
                    (
                        other.lineno for other in comprehensions
                        if other is not comp and other.lineno > comp.lineno
                        and _comprehension_uses_identity(other)
                    ),
                    default=float("inf"),
                )
                if guard is not None and comp.lineno < guard < later_selection:
                    continue
            else:
                guard = None
                # Selection is guarded only by a uniqueness check that appears
                # earlier in this function; later checks cannot repair it.
                for candidate in ast.walk(function):
                    if isinstance(candidate, ast.Compare) and candidate.lineno < comp.lineno:
                        # The selector's source collection must have been
                        # materialized as ``ids`` and checked before selection.
                        if _unique_guard_line(function, "ids") == candidate.lineno:
                            guard = candidate.lineno
                            break
                if guard is not None:
                    continue
            findings.append(f"{filename}:{comp.lineno}:uniqueness ordering")

    return findings


def _comprehension_uses_identity(comp: ast.ListComp | ast.GeneratorExp) -> bool:
    if not comp.generators or not isinstance(comp.generators[0].target, ast.Name):
        return False
    variable = comp.generators[0].target.id
    return _uses_id(comp.elt, variable) or any(
        _uses_id(predicate, variable)
        for generator in comp.generators
        for predicate in generator.ifs
    )


def _git(*args: str, root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _changed_py_files(root: Path | None = None) -> list[Path]:
    root = root or Path(__file__).resolve().parent.parent
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", root=root)
    if branch in {"main", "master", "HEAD"}:
        base = "HEAD^"
    elif _git("show-ref", "--verify", "--quiet", "refs/heads/main", root=root) is not None:
        base = "main"
    elif _git("show-ref", "--verify", "--quiet", "refs/heads/master", root=root) is not None:
        base = "master"
    else:
        base = "HEAD^"

    output = _git("diff", "--name-only", base, "--", "slopforge", root=root)
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", "slopforge", root=root)
    paths = set(output.splitlines() if output else ())
    paths.update(untracked.splitlines() if untracked else ())
    return sorted(
        root / path for path in paths
        if path.endswith(".py") and Path(path).parts[0] == "slopforge"
    )


def _main() -> int:
    root = Path(__file__).resolve().parent.parent
    findings: list[str] = []
    for path in _changed_py_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for finding in inspect_source(source, str(path.relative_to(root))):
            line = int(finding.split(":", 2)[1])
            function = next(
                (
                    node.name for node in ast.walk(ast.parse(source))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and _DECISION_NAME.search(node.name)
                    and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
                ),
                None,
            )
            if function:
                findings.append(f"{path.relative_to(root)}:{function}:{line}:{finding.rsplit(':', 1)[-1]}")

    for finding in findings:
        print(finding)
    if findings:
        return 1
    print("No provenance antipatterns detected.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
