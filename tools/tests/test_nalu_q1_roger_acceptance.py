"""apply_roger_q1_acceptance (nalu_pipeline, SUPERVISOR_ORDERS seq=31): order-keyed acceptance of
CHARACTER-IDENTITY-ADMISSION failures at S5 Q1 — never self-issued, sha-bound, other gates untouched."""
import json, sys, types, unittest
from pathlib import Path
import tempfile

TOOLS = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))
import nalu_pipeline as npl  # noqa: E402
import roger_gate_acceptance as rga  # noqa: E402


def _ctx(tmp: Path):
    p = types.SimpleNamespace(preprod_reports=tmp / "reports")
    return types.SimpleNamespace(episode="E06", p=p)


def _fixture(tmp: Path, *, extra_failure: str | None = None):
    q1 = tmp / "reports/qa/q1/E06-VU-004"; q1.mkdir(parents=True)
    ar = q1 / "admission_result.json"
    ar.write_text(json.dumps({"status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED", "asset_sha256": "abc",
                              "failures": ["required_registered_gate_not_pass:CHARACTER-IDENTITY-ADMISSION"]}))
    ident = tmp / "reports/qa/E06_KEYFRAME_IDENTITY_ADMISSION.json"
    ident.write_text(json.dumps({"objective_verification": {"decisions": [
        {"source_id": "E06:STILL:E06-S02-01", "character_id": "CHAR-QINMING", "aggregate_median": 0.288, "decision": "FAIL"}]}}))
    failures = ["evidence_1:CHARACTER-IDENTITY-ADMISSION:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
                "required_registered_gate_not_pass:CHARACTER-IDENTITY-ADMISSION"]
    if extra_failure:
        failures.append(extra_failure)
    index = {"unit_count": 2, "admitted_count": 1, "status": "PARTIAL_1_OF_2_ADMITTED",
             "video_submission_allowed_unit_ids": ["E06-VU-001"], "rejected_unit_ids": ["E06-VU-004"],
             "identity_measurement": {"engine_report": str(ident)},
             "results": [{"unit_id": "E06-VU-001", "item_id": "E06-S01-01", "status": "PASS", "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT"},
                         {"unit_id": "E06-VU-004", "item_id": "E06-S02-01", "status": "FAIL", "downstream_status": "FAIL_NOT_ADMITTED",
                          "asset_sha256": "abc", "failures": failures, "admission_result": str(ar)}]}
    ip = tmp / "reports/qa/q1/E06_KEYFRAME_Q1_INDEX.json"; ip.write_text(json.dumps(index))
    return index, ip, ar


def _order(sha="abc", detectors=("E06-S02-01:CHAR-QINMING",), status="active"):
    return {"seq": 31, "issued_by": "Roger", "status": status, "order": "c",
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E06", "gate_id": "CHARACTER-IDENTITY-ADMISSION",
                         "detectors": list(detectors), "media_sha256": None, "media_sha256_by_item": {"E06-S02-01": sha}}}


class RogerQ1AcceptanceTests(unittest.TestCase):
    def run_case(self, orders, **fx):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d); index, ip, ar = _fixture(tmp, **fx)
            saved = rga._orders
            rga._orders = lambda path: orders
            try:
                out = npl.apply_roger_q1_acceptance(_ctx(tmp), index, ip)
            finally:
                rga._orders = saved
            flags = {"engine_copy": (tmp / "reports/qa/q1/E06-VU-004/admission_result.engine.json").is_file(),
                     "record": (tmp / "reports/qa/q1/E06_ROGER_GATE_ACCEPTANCE.json").is_file()}
            return out, json.loads(ip.read_text()), json.loads(ar.read_text()), flags

    def test_no_order_stays_rejected(self):
        out, index, ar, _ = self.run_case([])
        self.assertEqual(out["still_rejected_unit_ids"], ["E06-VU-004"]); self.assertEqual(index["status"], "PARTIAL_1_OF_2_ADMITTED")
        self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_sha_mismatch_or_inactive_stays_rejected(self):
        for orders in ([_order(sha="zzz")], [_order(status="done")], [_order(detectors=("E06-S02-01:CHAR-LUZE",))]):
            out, index, ar, _ = self.run_case(orders)
            self.assertEqual(out["accepted_unit_ids"], []); self.assertEqual(ar["downstream_status"], "FAIL_NOT_ADMITTED")

    def test_other_gate_failing_is_never_accepted(self):
        out, index, ar, _ = self.run_case([_order()], extra_failure="required_registered_gate_not_pass:PERIOD-ANACHRONISM-LOCK")
        self.assertEqual(out["accepted_unit_ids"], [])

    def test_full_match_admits_by_order_and_keeps_engine_copy(self):
        out, index, ar, flags = self.run_case([_order()])
        self.assertEqual(out["accepted_unit_ids"], ["E06-VU-004"]); self.assertEqual(index["status"], "ALL_ADMITTED")
        self.assertIn("E06-VU-004", index["video_submission_allowed_unit_ids"])
        self.assertEqual(ar["downstream_status"], "ADMITTED_FOR_VIDEO_SUBMIT"); self.assertEqual(ar["status"], "ADMITTED_BY_LINE_OWNER_ORDER")
        self.assertEqual(ar["engine_status"], "FAIL"); self.assertEqual(ar["roger_acceptance"]["order_seq"], 31)
        self.assertTrue(flags["engine_copy"]); self.assertTrue(flags["record"])


if __name__ == "__main__":
    unittest.main()
