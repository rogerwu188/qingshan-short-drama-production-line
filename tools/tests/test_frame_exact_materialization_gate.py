import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.frame_exact_materialization_gate import evaluate


class FrameExactMaterializationGateTests(unittest.TestCase):
    def test_bound_render_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.json"
            video = root / "out.mp4"
            report = root / "out.render.json"
            plan.write_text(json.dumps({"segments": [{"source_id": "S1"}]}), encoding="utf-8")
            video.write_bytes(b"video")
            report.write_text(json.dumps({
                "status": "PASS",
                "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "segment_count": 1,
            }), encoding="utf-8")
            self.assertEqual(evaluate(plan, report, video)["status"], "PASS")

    def test_wrong_video_sha_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.json"
            video = root / "out.mp4"
            report = root / "out.render.json"
            plan.write_text(json.dumps({"segments": []}), encoding="utf-8")
            video.write_bytes(b"video")
            report.write_text(json.dumps({
                "status": "PASS",
                "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "output_sha256": "0" * 64,
                "segment_count": 0,
            }), encoding="utf-8")
            self.assertEqual(evaluate(plan, report, video)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
