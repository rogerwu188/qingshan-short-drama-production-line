import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import merge_incremental_image_admissions as merger


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


class MergeIncrementalImageAdmissionsTest(unittest.TestCase):
    def test_later_non_rejected_candidate_replaces_rejected_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "old.png"
            new = root / "new.png"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            write_json(root / "base.json", {"episode": "E30", "selections": []})
            write_json(root / "plan.json", {"episode": "E30", "tasks": [{"shot_id": "E30-CW-S01-SH03-C1"}]})
            write_json(root / "h1.json", {"results": [{
                "task_key": "E30-CW-S01-SH03-C1-STILL-R1", "task_id": "old", "remote_status": "completed",
                "output_path": str(old), "sha256": hashlib.sha256(b"old").hexdigest(),
            }]})
            write_json(root / "h2.json", {"results": [{
                "task_key": "E30-CW-S01-SH03-C1-STILL-R2", "task_id": "new", "remote_status": "completed",
                "output_path": str(new), "sha256": hashlib.sha256(b"new").hexdigest(),
            }]})
            write_json(root / "adjudication.json", {
                "default_completed_candidate_decision": "CONDITIONAL_MACHINE_ADMISSION",
                "default_confidence": 0.8,
                "default_selection_reason": "usable",
                "default_replacement_condition": "later pass",
                "capability_failure": {"status": "CAPABILITY_FAIL", "failure_items": ["runtime"]},
                "task_overrides": {"E30-CW-S01-SH03-C1-STILL-R1": {"decision": "REJECT", "failure_items": ["extra_person"]}},
            })
            argv = [
                "merge", "--base", "base.json", "--full-state-plan", "plan.json",
                "--harvest", "h1.json", "--harvest", "h2.json",
                "--adjudication", "adjudication.json", "--out", "out.json",
            ]
            with patch.object(merger, "ROOT", root), patch.object(sys, "argv", argv):
                self.assertEqual(merger.main(), 0)
            result = json.loads((root / "out.json").read_text())
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["selections"][0]["task_id"], "new")
            self.assertEqual(result["selections"][0]["raw_status"], "CAPABILITY_FAIL")
            self.assertEqual(result["rejected_candidates"][0]["failure_items"], ["extra_person"])


if __name__ == "__main__":
    unittest.main()
