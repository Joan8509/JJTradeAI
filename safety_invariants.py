"""Verifica invariantes estaticos de PAPER y aprendizaje descriptivo."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable, Sequence


EXCLUDED_PARTS = {
    ".git",
    ".agents",
    ".codex",
    "exports",
    "tests",
    "venv",
    "__pycache__",
}
EXCLUDED_FILES: set[str] = set()
FORBIDDEN_CALLS = {
    "submit_order",
    "place_order",
    "create_order",
    "replace_order",
    "cancel_order",
    "cancel_orders",
    "close_position",
    "close_all_positions",
}
FORBIDDEN_IMPORT_PREFIXES = (
    "alpaca.trading",
    "alpaca_trade_api",
)
FORBIDDEN_ENDPOINT_FRAGMENTS = (
    "/v2/orders",
    "/v2/positions",
)
DECISION_CRITICAL_FILES = {
    "analysis_pipeline.py",
    "assessment_service.py",
    "decision_engine.py",
    "governance.py",
    "invalidation_engine.py",
    "panorama_engine.py",
    "risk_engine.py",
}
LEARNING_MODULE_PREFIXES = (
    "learning_context",
    "learning_engine",
)
FORBIDDEN_DECISION_PARAMETER_PARTS = (
    "advisory",
    "learning",
    "outcome",
    "performance",
    "positive_rate",
    "win_rate",
)


@dataclass(frozen=True)
class SafetyFinding:
    path: str
    line: int
    rule: str
    detail: str


def discover_python_sources(root: str | Path) -> tuple[Path, ...]:
    base = Path(root)
    return tuple(
        sorted(
            (
                path
                for path in base.rglob("*.py")
                if path.name not in EXCLUDED_FILES
                and not EXCLUDED_PARTS.intersection(path.relative_to(base).parts)
            ),
            key=lambda path: path.as_posix(),
        )
    )


def audit_safety_invariants(
    root: str | Path = ".",
    *,
    sources: Iterable[str | Path] | None = None,
) -> dict[str, object]:
    base = Path(root)
    selected = (
        tuple(Path(path) for path in sources)
        if sources is not None
        else discover_python_sources(base)
    )
    findings: list[SafetyFinding] = []
    parsed: dict[Path, ast.AST] = {}
    for path in selected:
        display = _display_path(path, base)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=display)
        except (OSError, UnicodeError, SyntaxError) as error:
            findings.append(
                SafetyFinding(display, 0, "SOURCE_PARSE", str(error))
            )
            continue
        parsed[path] = tree
        findings.extend(_audit_tree(tree, display, path.name))
    findings.extend(_audit_transitive_learning_dependencies(parsed, base))
    trading_rules = {
        "TRADING_IMPORT",
        "ORDER_MUTATION_CALL",
        "TRADING_ENDPOINT",
    }
    learning_rules = {
        "LEARNING_DECISION_IMPORT",
        "LEARNING_DECISION_PARAMETER",
        "LEARNING_DECISION_TRANSITIVE",
    }
    trading_findings = [item for item in findings if item.rule in trading_rules]
    learning_findings = [item for item in findings if item.rule in learning_rules]
    return {
        "status": "OK" if not findings else "BLOQUEADO",
        "source_count": len(selected),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
        "paper_only": not trading_findings,
        "order_execution": bool(trading_findings),
        "learning_isolated": not learning_findings,
        "learning_authority": "DESCRIPTIVA_NO_INFLUYE_DECISION",
        "authority": "INVARIANTES_ESTATICOS_NO_EJECUTAN_ORDENES",
    }


def _audit_tree(
    tree: ast.AST,
    display_path: str,
    filename: str,
) -> list[SafetyFinding]:
    findings: list[SafetyFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = _imported_modules(node)
            for module in modules:
                if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    findings.append(
                        SafetyFinding(
                            display_path,
                            node.lineno,
                            "TRADING_IMPORT",
                            f"Import de trading prohibido: {module}.",
                        )
                    )
                if (
                    filename in DECISION_CRITICAL_FILES
                    and module.startswith(LEARNING_MODULE_PREFIXES)
                ):
                    findings.append(
                        SafetyFinding(
                            display_path,
                            node.lineno,
                            "LEARNING_DECISION_IMPORT",
                            f"Modulo de decision importa aprendizaje: {module}.",
                        )
                    )
        elif isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            if call_name in FORBIDDEN_CALLS:
                findings.append(
                    SafetyFinding(
                        display_path,
                        node.lineno,
                        "ORDER_MUTATION_CALL",
                        f"Llamada de ejecucion/mutacion prohibida: {call_name}.",
                    )
                )
        elif (
            filename != "safety_invariants.py"
            and isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        ):
            lowered = node.value.lower()
            for fragment in FORBIDDEN_ENDPOINT_FRAGMENTS:
                if fragment in lowered:
                    findings.append(
                        SafetyFinding(
                            display_path,
                            getattr(node, "lineno", 0),
                            "TRADING_ENDPOINT",
                            f"Endpoint de trading prohibido: {fragment}.",
                        )
                    )
        if (
            filename == "decision_engine.py"
            and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "build_decision"
        ):
            for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                lowered = argument.arg.lower()
                if any(part in lowered for part in FORBIDDEN_DECISION_PARAMETER_PARTS):
                    findings.append(
                        SafetyFinding(
                            display_path,
                            argument.lineno,
                            "LEARNING_DECISION_PARAMETER",
                            f"Parametro de aprendizaje prohibido: {argument.arg}.",
                        )
                    )
    return findings


def _audit_transitive_learning_dependencies(
    parsed: dict[Path, ast.AST],
    root: Path,
) -> list[SafetyFinding]:
    """Impide que decision alcance aprendizaje a traves de helpers locales."""
    module_paths = {path.stem: path for path in parsed}
    imports: dict[str, set[str]] = {}
    for path, tree in parsed.items():
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported.update(
                    module.split(".", 1)[0]
                    for module in _imported_modules(node)
                    if module
                )
        imports[path.stem] = imported

    findings: list[SafetyFinding] = []
    critical_stems = {
        Path(filename).stem for filename in DECISION_CRITICAL_FILES
    }
    for origin in sorted(critical_stems.intersection(module_paths)):
        queue: list[tuple[str, tuple[str, ...]]] = [(origin, (origin,))]
        visited = {origin}
        while queue:
            module, route = queue.pop(0)
            for dependency in sorted(imports.get(module, ())):
                next_route = (*route, dependency)
                if dependency.startswith(LEARNING_MODULE_PREFIXES):
                    if module == origin:
                        continue  # La dependencia directa ya tiene una regla precisa.
                    path = module_paths[origin]
                    findings.append(
                        SafetyFinding(
                            _display_path(path, root),
                            0,
                            "LEARNING_DECISION_TRANSITIVE",
                            "Dependencia indirecta hacia aprendizaje: "
                            + " -> ".join(next_route)
                            + ".",
                        )
                    )
                    continue
                if dependency in module_paths and dependency not in visited:
                    visited.add(dependency)
                    queue.append((dependency, next_route))
    return findings


def _imported_modules(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    return (node.module or "",)


def _call_name(function: ast.expr) -> str:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", help="Ruta opcional para el JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = audit_safety_invariants(args.root)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
