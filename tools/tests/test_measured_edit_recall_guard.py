import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
from build_measured_edit_constraints import build_measured_edit_constraints  # noqa: E402


class RecallGuardTests(unittest.TestCase):
    """A trim measured from ASR that misses a scripted line must not cut that line away (E14-VU-001)."""

    def _fixture(self, root: Path, recall: float):
        video = root / "video"; video.mkdir()
        media = video / "U1.mp4"; media.write_bytes(b"x")
        pg = root / "pg" / "U1"; pg.mkdir(parents=True)
        (pg / "U1_POST_GENERATION_QA.json").write_text(json.dumps({
            "unit_id": "U1", "media_path": str(media), "media_sha256": "a" * 64,
            "dialogue_qa": {"status": "PASS", "recall_score": recall, "expected_line_count": 2,
                            "segments": [{"start": 2.7, "end": 4.7, "text": "line two only"}]}}))
        plan = root / "plan.json"
        plan.write_text(json.dumps({"units": [{"unit_id": "U1", "duration_seconds": 8.0}]}))
        return root / "pg", video, plan

    def run_build(self, recall):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pg, video, plan = self._fixture(root, recall)
            out = root / "c.json"
            build_measured_edit_constraints(episode="E0", postgen_dir=pg, video_media=video, grouping_plan=plan,
                                            out_constraints=out, out_evidence_dir=root / "ev")
            return json.loads(out.read_text())

    def test_low_recall_keeps_full_length(self):
        got = self.run_build(0.765)
        self.assertEqual(got["units"], [])

    def test_complete_recall_still_trims(self):
        got = self.run_build(1.0)
        self.assertEqual(len(got["units"]), 1)
        self.assertAlmostEqual(got["units"][0]["recommended_source_out_seconds"], 4.82, places=2)


if __name__ == "__main__":
    unittest.main()
