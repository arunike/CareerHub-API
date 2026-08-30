import ast
import io
from pathlib import Path

from django.test import SimpleTestCase

SOURCE_ROOT = Path(__file__).resolve().parent.parent.parent
SKIP_DIRS = {"__pycache__", "migrations", "node_modules", ".venv", "venv"}


def _python_files():
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _relative(path):
    return path.relative_to(SOURCE_ROOT)


class CommentStyleTests(SimpleTestCase):
    """AGENTS.md comment rules, enforced here so a violation fails the suite, not a review."""

    def test_the_sweep_actually_reads_the_source(self):
        """A silent zero would make every assertion below vacuous."""
        self.assertGreater(len(list(_python_files())), 50)

    def test_no_comment_runs_longer_than_one_line(self):
        offenders = []
        for path in _python_files():
            lines = io.open(path, encoding="utf-8").read().splitlines()
            start = count = 0
            for number, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#") and not stripped.startswith("#!"):
                    if count == 0:
                        start = number
                    count += 1
                    continue
                if count > 1:
                    offenders.append(f"{_relative(path)}:{start} has {count} comment lines")
                count = 0
            if count > 1:
                offenders.append(f"{_relative(path)}:{start} has {count} comment lines")
        self.assertEqual(offenders, [], "One line — cut it, do not reflow it:\n" + "\n".join(offenders))

    def test_no_docstring_runs_longer_than_one_line(self):
        offenders = []
        for path in _python_files():
            tree = ast.parse(io.open(path, encoding="utf-8").read(), str(path))
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                doc = ast.get_docstring(node)
                if doc and len(doc.strip().splitlines()) > 1:
                    offenders.append(f"{_relative(path)}:{node.lineno} {node.name}")
        self.assertEqual(offenders, [], "One line — cut it, do not reflow it:\n" + "\n".join(offenders))

    def test_no_module_docstrings(self):
        """A module docstring is a file-header essay in another syntax."""
        offenders = [
            str(_relative(path))
            for path in _python_files()
            if ast.get_docstring(ast.parse(io.open(path, encoding="utf-8").read(), str(path)))
        ]
        self.assertEqual(offenders, [], "Docstrings go on the callable:\n" + "\n".join(offenders))
