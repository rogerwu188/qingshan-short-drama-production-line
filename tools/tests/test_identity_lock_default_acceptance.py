"""Device 1205 E17 (2026-11-28): a receipted CHARACTER-IDENTITY-ADMISSION default acceptance bound to the
reviewed identity plate admits a VLM-rejected subject at the S3 identity lock; anything looser does not."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

ISSUER = "Roger"


def _order(base: Path, plate_sha: str, *, detectors, gate="CHARACTER-IDENTITY-ADMISSION", episode="E17",
           seq=335, binding=None):
    text = "default acceptance: quality never blocks the line"
    receipt = {"schema": "qingshan.line_owner_order_source_receipt.v1", "status": "CONFIRMED",
               "issued_by": ISSUER, "order_seq": seq, "order_id": f"ord-{seq}", "verbatim": text,
               "recorded_at_utc": "2026-11-28T16:10:00Z"}
    rpath = base / f"receipt_{seq}.json"
    rpath.write_text(json.dumps(receipt))
    decision = {"kind": "GATE_FAIL_ACCEPTANCE", "episode": episode, "gate_id": gate, "detectors": detectors}
    decision.update(binding if binding is not None else {"media_sha256_by_item": {"CHAR-JOHN-SIMS": plate_sha}})
    return {"seq": seq, "id": f"ord-{seq}", "status": "active", "issued_by": ISSUER, "order": text,
            "decision": decision,
            "source_receipt": {"path": str(rpath), "sha256": hashlib.sha256(rpath.read_bytes()).hexdigest()}}


class IdentityLockDefaultAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.lock = importlib.import_module("identity_qa_lock")
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.plate = self.base / "CHAR-JOHN-SIMS_front.png"
        self.plate.write_bytes(b"plate-bytes")
        self.sha = hashlib.sha256(b"plate-bytes").hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def _accept(self, orders, **kw):
        args = dict(episode="E17", asset_id="CHAR-JOHN-SIMS", verdict="REJECT", plates=[self.plate],
                    issuer=ISSUER, review_path=self.base / "review.json")
        args.update(kw)
        return self.lock.line_owner_identity_acceptance(orders, **args)

    def test_plate_bound_subject_order_admits(self):
        rec = self._accept([_order(self.base, self.sha, detectors=["CHAR-JOHN-SIMS:HAIR_LENGTH_DIFFERS"])])
        self.assertIsNotNone(rec)
        self.assertEqual(rec["order_seq"], 335)
        self.assertEqual(rec["gate_status_kept"], "FAIL")
        self.assertEqual(rec["review_verdict_kept"], "REJECT")

    def test_plain_media_sha_binding_admits(self):
        rec = self._accept([_order(self.base, self.sha, detectors=["CHAR-JOHN-SIMS:HAIR_LENGTH_DIFFERS"],
                                   binding={"media_sha256": self.sha})])
        self.assertIsNotNone(rec)

    def test_wrong_plate_sha_refused(self):
        self.assertIsNone(self._accept([_order(self.base, "b" * 64, detectors=["CHAR-JOHN-SIMS:HAIR"])]))

    def test_other_subject_other_gate_other_episode_refused(self):
        self.assertIsNone(self._accept([_order(self.base, self.sha, detectors=["CHAR-LEVI:HAIR"])]))
        self.assertIsNone(self._accept([_order(self.base, self.sha, detectors=["CHAR-JOHN-SIMS:HAIR"],
                                               gate="VIDEO-Q2-ASSEMBLY-ADMISSION")]))
        self.assertIsNone(self._accept([_order(self.base, self.sha, detectors=["CHAR-JOHN-SIMS:HAIR"],
                                               episode="E16")]))

    def test_wrong_issuer_or_no_receipt_refused(self):
        order = _order(self.base, self.sha, detectors=["CHAR-JOHN-SIMS:HAIR"])
        self.assertIsNone(self._accept([order], issuer="someone-else"))
        order.pop("source_receipt")
        self.assertIsNone(self._accept([order]))


if __name__ == "__main__":
    unittest.main()
