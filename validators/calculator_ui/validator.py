from __future__ import annotations

import ast
import os
import py_compile
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str


@dataclass
class ValidationResult:
    project_dir: Path
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, message: str) -> None:
        self.checks.append(CheckResult(name=name, passed=passed, message=message))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _candidate_project_dirs(path: Path) -> list[Path]:
    """Build search paths for WareHouse runs (handles common mis-set env vars)."""
    path = Path(path).expanduser()
    repo = _repo_root()
    chatdev_warehouse = repo / "demos" / "chatdev-ollama" / "ChatDev-Ollama" / "WareHouse"
    name = path.name or str(path).replace("\\", "/").split("/")[-1]

    candidates: list[Path] = [path]
    if not path.is_absolute():
        candidates.append(repo / path)
    # e.g. CALCULATOR_PROJECT_DIR=WareHouse/calculator-14_... (wrong: repo has no WareHouse/)
    if name.startswith("calculator") or "ProgramDevOrg" in name:
        candidates.append(chatdev_warehouse / name)
    return candidates


def find_project_root(path: Path) -> Path:
    """Resolve a directory that contains main.py (project root or direct child)."""
    tried: list[str] = []
    for candidate in _candidate_project_dirs(path):
        try:
            resolved = candidate.resolve()
        except OSError:
            tried.append(str(candidate))
            continue
        tried.append(str(resolved))
        if (resolved / "main.py").is_file():
            return resolved
        if resolved.is_dir():
            for child in sorted(resolved.iterdir()):
                if child.is_dir() and (child / "main.py").is_file():
                    return child
    raise FileNotFoundError(
        "No main.py found for calculator validation. Tried:\n  "
        + "\n  ".join(tried)
        + "\n\nSet CALCULATOR_PROJECT_DIR to the ChatDev WareHouse run folder, e.g.\n"
        "  demos\\chatdev-ollama\\ChatDev-Ollama\\WareHouse\\calculator-14_ProgramDevOrg_20260601145603\n"
        "Or unset it to use the in-repo reference fixture."
    )


def _uses_tkinter(project_dir: Path) -> bool:
    pattern = re.compile(r"\b(import\s+tkinter|from\s+tkinter\s+import)\b")
    for py_file in project_dir.rglob("*.py"):
        if py_file.name.startswith("."):
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if pattern.search(text):
            return True
    return False


def _main_has_dunder_main(project_dir: Path) -> bool:
    main_path = project_dir / "main.py"
    text = main_path.read_text(encoding="utf-8", errors="replace")
    return "if __name__" in text and "__main__" in text


def _compile_all(project_dir: Path) -> list[str]:
    errors: list[str] = []
    for py_file in project_dir.rglob("*.py"):
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{py_file.relative_to(project_dir)}: {exc.msg}")
    return errors


def validate_static(project_dir: Path, result: ValidationResult) -> None:
    main_path = project_dir / "main.py"
    result.add("main_py_exists", main_path.is_file(), f"Expected {main_path}")

    if not main_path.is_file():
        return

    if sys.version_info < (3, 10):
        result.add("python_version", False, f"Python 3.10+ required, got {sys.version}")
    else:
        result.add("python_version", True, f"Python {sys.version_info.major}.{sys.version_info.minor}")

    compile_errors = _compile_all(project_dir)
    result.add(
        "python_syntax",
        not compile_errors,
        "All .py files compile" if not compile_errors else "; ".join(compile_errors[:5]),
    )

    uses_tk = _uses_tkinter(project_dir)
    result.add("uses_tkinter", uses_tk, "Found tkinter import in project" if uses_tk else "No tkinter import found")

    has_main_guard = _main_has_dunder_main(project_dir)
    result.add(
        "main_guard",
        has_main_guard,
        "main.py contains if __name__ == '__main__'" if has_main_guard else "Missing __main__ guard in main.py",
    )

    try:
        ast.parse(main_path.read_text(encoding="utf-8"))
        result.add("main_ast_parse", True, "main.py parses as valid Python")
    except SyntaxError as exc:
        result.add("main_ast_parse", False, str(exc))


def validate_project(project_path: Path) -> ValidationResult:
    """
    Validate a generated CalculatorUI directory: static checks + black-box behavior pytest suite.
    """
    import pytest

    result = ValidationResult(project_dir=project_path)
    try:
        project_dir = find_project_root(project_path)
        result.project_dir = project_dir
    except FileNotFoundError as exc:
        result.add("project_layout", False, str(exc))
        return result

    result.add("project_layout", True, f"Using project root {project_dir}")
    validate_static(project_dir, result)

    prev = os.environ.get("CALCULATOR_PROJECT_DIR")
    os.environ["CALCULATOR_PROJECT_DIR"] = str(project_dir)
    try:
        exit_code = pytest.main(
            [str(Path(__file__).parent), "-q", "--tb=line"],
        )
    finally:
        if prev is None:
            os.environ.pop("CALCULATOR_PROJECT_DIR", None)
        else:
            os.environ["CALCULATOR_PROJECT_DIR"] = prev

    result.add(
        "pytest_calculator_suite",
        exit_code == 0,
        "All pytest behavior tests passed"
        if exit_code == 0
        else f"pytest failed (exit {exit_code}); run: pytest validators/calculator_ui -v",
    )
    return result
