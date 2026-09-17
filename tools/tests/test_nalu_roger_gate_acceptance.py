"""roger_gate_acceptance: only an explicit, matching, active Roger order accepts a gate FAIL."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("roger_gate_acceptance",
                                              ROOT / "lines/nalu/runtime/tools/roger_gate_acceptance.py")
mod = importlib.util.module_from_spec(SPEC)
sys.modules["roger_gate_acceptance"] = mod
SPEC.loader.exec_module(mod)

ORDER = {"seq": 24, "id": "X", "issued_by": "Roger", "status": "active", "order": "「1」",
         "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E04", "gate_id": "G",
                      "detectors": ["a", "b"], "media_sha256": None}}


class Acceptance(unittest.TestCase):
    def test_matching_order_is_found(self):
        self.assertIs(mod.find_acceptance([ORDER], episode="E04", gate_id="G", failing=["a"], media_sha256="s"), ORDER)

    def test_new_failing_detector_is_not_covered(self):
        self.assertIsNone(mod.find_acceptance([ORDER], episode="E04", gate_id="G", failing=["a", "c"], media_sha256="s"))

    def test_other_episode_gate_issuer_or_status_do_not_match(self):
        for patch in ({"issued_by": "claude"}, {"status": "superseded"},
                      {"decision": {**ORDER["decision"], "episode": "E05"}},
                      {"decision": {**ORDER["decision"], "gate_id": "H"}},
                      {"decision": {**ORDER["decision"], "kind": "OTHER"}}):
            row = {**ORDER, **patch}
            self.assertIsNone(mod.find_acceptance([row], episode="E04", gate_id="G", failing=["a"], media_sha256="s"), patch)

    def test_bound_media_sha_must_match(self):
        row = {**ORDER, "decision": {**ORDER["decision"], "media_sha256": "abc"}}
        self.assertIsNone(mod.find_acceptance([row], episode="E04", gate_id="G", failing=["a"], media_sha256="zzz"))
        self.assertIs(mod.find_acceptance([row], episode="E04", gate_id="G", failing=["a"], media_sha256="abc"), row)

    def test_record_keeps_fail_and_is_never_self_issued(self):
        rec = mod.acceptance_record(ORDER, episode="E04", gate_id="G", failing=["b", "a"], media_sha256="s", gate_result_path="r.json")
        self.assertEqual(rec["gate_status_kept"], "FAIL")
        self.assertEqual(rec["accepted_detectors"], ["a", "b"])
        self.assertFalse(rec["self_issued"])
        self.assertEqual(rec["order_verbatim"], "「1」")

    def test_failing_detectors_from_gate_result(self):
        self.assertEqual(mod.failing_detectors({"detectors": {"a": "FAIL", "b": "PASS"}}), ["a"])
        self.assertEqual(mod.failing_detectors({"failures": ["x:FAIL:code", "y:FAIL"]}), ["x", "y"])


if __name__ == "__main__":
    unittest.main()
