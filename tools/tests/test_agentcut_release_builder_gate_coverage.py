import ast
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUARD = "require_release_builder_gate_admission"
RENDER_CALL_NAMES = {"render_unit", "build_bgm_stem", "prepare_u19", "run"}


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            names.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            names.add(f"{getattr(child.func.value, 'id', '')}.{child.func.attr}")
    return names


def coverage_failures(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == GUARD for alias in node.names)
            for node in ast.walk(tree)
        )
        called = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == GUARD
            for node in ast.walk(tree)
        )
        main = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
            None,
        )
        guard_index = None
        first_render_index = None
        if main is not None:
            for index, statement in enumerate(main.body):
                names = _call_names(statement)
                if GUARD in names and guard_index is None:
                    guard_index = index
                if names & (RENDER_CALL_NAMES | {"subprocess.run"}) and first_render_index is None:
                    first_render_index = index
        guard_precedes_render = (
            guard_index is not None
            and (first_render_index is None or guard_index < first_render_index)
        )
        if not imported or not called or not guard_precedes_render:
            failures.append(path.name)
    return failures


class AgentCutReleaseBuilderGateCoverageTests(unittest.TestCase):
    def test_every_episode_agentcut_release_builder_calls_unified_gate_runner(self):
        builders = sorted((ROOT / "tools").glob("build_e*_agentcut_release.py"))
        self.assertGreaterEqual(len(builders), 3)
        self.assertEqual(coverage_failures(builders), [])

    def test_new_builder_without_guard_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build_e99_agentcut_release.py"
            path.write_text("def main():\n    return 0\n", encoding="utf-8")
            self.assertEqual(coverage_failures([path]), [path.name])

    def test_guard_added_after_render_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build_e99_agentcut_release.py"
            path.write_text(
                "from tools.episode_stage_gate_runner import require_release_builder_gate_admission\n"
                "def main():\n"
                "    render_unit()\n"
                "    require_release_builder_gate_admission()\n",
                encoding="utf-8",
            )
            self.assertEqual(coverage_failures([path]), [path.name])


if __name__ == "__main__":
    unittest.main()
