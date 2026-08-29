import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class E40R04DialogueOrderTest(unittest.TestCase):
    def test_canonical_evidence_precedes_denial_and_accusation(self) -> None:
        tree = ast.parse((ROOT / "tools/build_e40_current_sequence_v6_all_dialogue_covered.py").read_text())
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SEGMENTS" for target in node.targets)
        )
        segments = ast.literal_eval(assignment.value)
        ids = [row[0] for row in segments]
        self.assertLess(ids.index("R04-CHENJI-A"), ids.index("R04"))
        self.assertLess(ids.index("R04"), ids.index("R04-YUNFEI-B"))


if __name__ == "__main__":
    unittest.main()
