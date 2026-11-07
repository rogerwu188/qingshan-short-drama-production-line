"""S7 releases a rejected/failed final cut only on a line-owner default-terms order bound to the candidate sha
(line owner 2026-11-07, field device …1324 E01: a rejected final review must not stop ~100 unattended machines)."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402

QA = {"stage_gate_rows": [{"gate_id": "AUDIENCE-SCORE", "status": "FAIL"},
                          {"gate_id": "FINAL-CUT-QUALITY", "status": "REJECT_RECUT"},
                          {"gate_id": "SUBTITLES", "status": "PASS"}],
      "stage_gate_summary": "/x/summary.json", "blockers": ["FINAL_PHASE_REGISTERED_GATE_EVIDENCE_OR_REVIEW_NOT_PASS"]}
EXPECTED = ["final:FINAL_AUDIENCE_REVIEW_REJECTED", "final:AUDIENCE-SCORE", "final:FINAL-CUT-QUALITY"]


class DefaultReleaseAcceptanceTest(unittest.TestCase):
    def ctx(self, tmp: Path):
        cand = tmp / "E01_final_candidate_9x16.mp4"
        cand.write_bytes(b"cut")
        (tmp / "final_qa").mkdir()
        return SimpleNamespace(episode="E01", p=SimpleNamespace(final_candidate=cand, assembly=tmp),
                               authority={"orders_path": str(tmp / "orders.json"), "line_owner_id": "owner",
                                          "latest_order_seq": 3},
                               authority_blockers=[], say=lambda *_a: None), hashlib.sha256(b"cut").hexdigest()

    def test_no_order_blocks_and_names_every_failure(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, _sha = self.ctx(Path(d))
            with mock.patch.object(npl._rga, "_orders", return_value=[]):
                out = npl.s7_default_release_acceptance(ctx, QA, True)
        self.assertEqual(out["status"], npl.BLOCKED)
        self.assertEqual(out["failing"], EXPECTED)
        self.assertTrue(out["blockers"][0].startswith("FINAL_RELEASE_DEFAULT_ACCEPTANCE_ORDER_REQUIRED:"))

    def test_bound_order_releases_and_keeps_fail(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, sha = self.ctx(Path(d))
            order = {"seq": 3, "id": "O3", "issued_by": "owner", "order": "默认条款",
                     "decision": {"media_sha256_by_item": {"final": sha}}}
            with mock.patch.object(npl._rga, "_orders", return_value=[order]), \
                    mock.patch.object(npl._rga, "find_acceptance", return_value=order) as find:
                out = npl.s7_default_release_acceptance(ctx, QA, True)
            self.assertEqual(find.call_args.kwargs["failing"], EXPECTED)
            self.assertEqual(find.call_args.kwargs["media_item_id"], "final")
            record = json.loads(Path(out["record_path"]).read_text(encoding="utf-8"))
        self.assertEqual(out["status"], npl.PASS)
        self.assertEqual(record["gate_status_kept"], "FAIL")
        self.assertTrue(record["final_audience_review_rejected"])

    def summary(self, tmp: Path, failures: dict[str, list[str]]) -> dict:
        path = tmp / "summary.json"
        path.write_text(json.dumps({"results": [{"gate_id": g, "status": "FAIL", "failures": f}
                                                for g, f in failures.items()]}), encoding="utf-8")
        return {"stage_gate_summary": str(path),
                "stage_gate_rows": [{"gate_id": g, "status": "FAIL", "first_failure": f[0]}
                                    for g, f in failures.items()]}

    def test_line_unproduced_evidence_is_released_on_the_order(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, _sha = self.ctx(Path(d))
            qa = self.summary(Path(d), {
                "RELEASE-SIGNOFF-INTEGRITY": ["required_evidence_missing:watch_report:missing:/rt/E01.APPROVED.json",
                                              "required_evidence_missing:ci_report:missing:/x"],
                "AUDIENCE-SCORE": ["verdict REJECT_RECUT"]})
            with mock.patch.object(npl._rga, "_orders", return_value=[]):
                out = npl.s7_default_release_acceptance(ctx, qa, False)
        self.assertEqual(out["failing"], ["final:AUDIENCE-SCORE", "final:RELEASE-SIGNOFF-INTEGRITY"])
        self.assertTrue(out["blockers"][0].startswith("FINAL_RELEASE_DEFAULT_ACCEPTANCE_ORDER_REQUIRED:"))

    def test_other_missing_evidence_is_never_released(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, _sha = self.ctx(Path(d))
            qa = self.summary(Path(d), {"FINAL-CUT-EVENT-LEDGER": ["required_evidence_missing:event_ledger:missing:/x"]})
            out = npl.s7_default_release_acceptance(ctx, qa, True)
        self.assertEqual(out, {"status": npl.BLOCKED, "blockers": ["FINAL_EVIDENCE_MISSING:FINAL-CUT-EVENT-LEDGER"]})

    def test_no_gate_rows_is_an_evidence_problem(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, _sha = self.ctx(Path(d))
            out = npl.s7_default_release_acceptance(ctx, {"blockers": ["X"]}, False)
        self.assertEqual(out, {"status": npl.BLOCKED, "blockers": ["X"]})


if __name__ == "__main__":
    unittest.main()
