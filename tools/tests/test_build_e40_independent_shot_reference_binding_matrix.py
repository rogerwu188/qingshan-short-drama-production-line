import hashlib
import json
import unittest
from pathlib import Path

from tools.build_e40_independent_shot_reference_binding_matrix import (
    ASSETS,
    MANIFEST_SHA,
    MATRIX_PATH,
    MODEL,
    QA_PATH,
    SCRIPT_SHA,
)


ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class E40IndependentShotReferenceBindingMatrixTests(unittest.TestCase):
    def test_matrix_covers_exact_independent_scope_and_canonical(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        expected = [*[f"U{i:02d}" for i in range(1, 17)], *[f"U{i:02d}" for i in range(24, 30)]]
        self.assertEqual([row["unit_id"] for row in matrix["units"]], expected)
        self.assertEqual(matrix["canonical"]["script_sha256"], SCRIPT_SHA)
        self.assertEqual(matrix["canonical"]["manifest_sha256"], MANIFEST_SHA)

    def test_existing_assets_and_prompts_are_exact_sha_bound(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        for asset in ASSETS.values():
            self.assertEqual(sha256(ROOT / asset["path"]), asset["sha256"])
        for row in matrix["units"]:
            self.assertEqual(sha256(Path(row["prompt_file"])), row["prompt_sha256"])
            self.assertEqual(row["model"], MODEL)
            self.assertFalse(row["paid_submission_allowed"])

    def test_no_character_card_is_misreported_as_exact_start_frame(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(matrix["classification_counts"]["DIRECT_SUBMIT_PACKAGE"], 0)
        for row in matrix["units"]:
            self.assertIsNone(row["first_frame"]["exact_shot_start_path"])
            self.assertIsNone(row["first_frame"]["exact_shot_start_sha256"])

    def test_shortest_path_and_classification_counts_are_stable(self):
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            matrix["classification_counts"],
            {"DIRECT_SUBMIT_PACKAGE": 0, "ONLY_LOCAL_COMPOSITE_START_FRAME_MISSING": 9, "MUST_CREATE_NEW_ASSET": 13},
        )
        self.assertEqual(matrix["shortest_path_first_complete_package"]["unit_id"], "U04")
        self.assertEqual(qa["status"], "PASS")
        self.assertEqual(qa["failures"], [])
        self.assertEqual(qa["matrix_sha256"], sha256(MATRIX_PATH))


if __name__ == "__main__":
    unittest.main()
