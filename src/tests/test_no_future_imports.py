"""
Guards the house rule that no Python file of the repository imports from `__future__`.

`Injector.inject` reads `Provide[T]` from the parameter annotations as `inspect.signature` returns them. Under
`from __future__ import annotations` every annotation is a string, `Provide[T]` is not recognised and the parameter
is silently not injected. The package, its tests and its scripts therefore write the syntax Python 3.11 evaluates.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRECTORIES = ["src", ".github/scripts"]


def python_files() -> list[Path]:
    """Every `.py` file under the scanned directories that exist in this checkout."""
    return [path
            for directory in SCANNED_DIRECTORIES if (ROOT / directory).is_dir()
            for path in sorted((ROOT / directory).rglob("*.py"))]


def future_import_lines(path: Path) -> list[int]:
    """The line numbers of the `__future__` imports in a Python file, in any form."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            lines.append(node.lineno)
        elif isinstance(node, ast.Import) and any(alias.name == "__future__" for alias in node.names):
            lines.append(node.lineno)
    return sorted(lines)


def test_detector_recognises_every_import_form(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("import os\n"
                      "from __future__ import annotations\n"
                      "import __future__\n"
                      "from __future__ import (\n"
                      "    annotations,\n"
                      "    division,\n"
                      ")\n", encoding="utf-8")
    assert future_import_lines(sample) == [2, 3, 4]


def test_no_future_imports():
    files = python_files()
    assert ROOT / "src" / "smalldi" / "__init__.py" in files
    offenders = [f"{path.relative_to(ROOT)}:{line}" for path in files for line in future_import_lines(path)]
    assert not offenders, "`__future__` imports are prohibited (see AGENTS.md, House rules):\n" + "\n".join(offenders)
