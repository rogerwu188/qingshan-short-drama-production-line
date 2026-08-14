import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "adjudicate_video_review_ocr_tail_gap", ROOT / "tools/adjudicate_video_review_ocr_tail_gap.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OcrTailGapAdjudicationTests(unittest.TestCase):
    def test_admits_only_small_tail_gap_with_required_capabilities_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "clip.mp4"
            media.write_bytes(b"video")
            review = root / "review.json"
            review.write_text(json.dumps({"items": [{
                "media_path": str(media),
                "media_sha256": MODULE.sha256(media),
                "status": "FAIL",
                "content_status": "CONTENT_FAIL",
                "issues": [
                    {"issue_id": "I1", "rule_id": "audio.info", "blocking": False},
                    {"issue_id": "Q1", "rule_id": "ocr.main_content_coverage_gap", "blocking": True},
                ],
                "capabilities": {
                    "media_probe": {"requirement": "REQUIRED", "status": "PASS"},
                    "video_analysis": {"requirement": "REQUIRED", "status": "PASS"},
                    "audio_analysis": {"requirement": "REQUIRED", "status": "PASS"},
                    "ocr": {"requirement": "OPTIONAL", "raw_status": "FAIL", "main_content_hit_count": 0,
                    "raw_recognition_count": 1, "raw_rejected_count": 1,
                    "raw_rejected_recognitions": [{"text": "C", "forbidden": False}], "review_window": {
                        "main_content_end_seconds": 9.055, "declared_review_end_seconds": 9.041
                    }, "supplemental_gap_scan": {"error": {"error_code": "OCR_GAP_SCAN_UNAVAILABLE"}}},
                },
                "agentcut": {"clip_id": "U11"},
            }]}), encoding="utf-8")
            result = MODULE.adjudicate(review, root / "admission.json", 0.05)
            self.assertFalse(result["blocking"])
            self.assertEqual(result["admissions"][0]["decision"], "CONDITIONAL_MACHINE_ADMISSION")

    def test_rejects_content_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "review.json"
            review.write_text(json.dumps({"items": [{"issues": [{"rule_id": "identity.mismatch", "blocking": True}]}]}))
            with self.assertRaisesRegex(ValueError, "non-OCR-tail blocking"):
                MODULE.adjudicate(review, root / "out.json", 0.05)


if __name__ == "__main__":
    unittest.main()
