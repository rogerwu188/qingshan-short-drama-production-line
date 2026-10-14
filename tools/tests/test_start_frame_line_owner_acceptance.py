"""Start-frame semantic evidence: a failing derived start frame is accepted only by an exact, sha-bound,
source-receipted line-owner order that names every gap; the validator waives exactly those gaps."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
import roger_gate_acceptance as rga  # noqa: E402
import start_frame_evidence_writer as sfw  # noqa: E402
import action_role_evidence_writer as arw  # noqa: E402
from tools.shot_media_admission_gate import _validate_action_role_verification  # noqa: E402
from tools.grouped_anchor_semantic_contract import validate_start_anchor_semantics  # noqa: E402

UNIT = "E02-VU-004"
BLOCKERS = ["VLM_REVIEW_REJECT", "REQUIRED_CHARACTER_NOT_OBSERVED:沈青", "REQUIRED_PROP_NOT_OBSERVED:茶壶",
            "START_FRAME_NOT_ENTRY_STATE_ONLY"]


def _order(tmp: Path, *, detectors, sha, seq=11, gate=sfw.START_FRAME_GATE_ID):
    verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
    receipt = {"schema": rga.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": "owner-1",
               "order_seq": seq, "order_id": f"ACCEPT-{seq}", "verbatim": verbatim,
               "recorded_at_utc": "2026-10-14T00:00:00Z"}
    path = tmp / f"receipt-{seq}.json"
    path.write_text(json.dumps(receipt))
    return {"seq": seq, "id": f"ACCEPT-{seq}", "issued_by": "owner-1", "status": "active", "order": verbatim,
            "source_receipt": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E02", "gate_id": gate,
                         "detectors": list(detectors), "media_sha256_by_item": {UNIT: sha}}}


class WriterAcceptanceTests(unittest.TestCase):
    def test_blocker_detectors_split_lists(self):
        self.assertEqual(sfw.blocker_detectors(UNIT, ["REQUIRED_CHARACTER_NOT_OBSERVED:沈青,陆九", "VLM_REVIEW_REJECT"]),
                         [f"{UNIT}:REQUIRED_CHARACTER_NOT_OBSERVED:沈青", f"{UNIT}:REQUIRED_CHARACTER_NOT_OBSERVED:陆九",
                          f"{UNIT}:VLM_REVIEW_REJECT"])

    def test_full_order_accepts_partial_or_integrity_does_not(self):
        sha = "c" * 64
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            full = _order(tmp, detectors=sfw.blocker_detectors(UNIT, BLOCKERS), sha=sha)
            record = sfw.start_frame_acceptance("E02", UNIT, BLOCKERS, sha, [full], "owner-1")
            self.assertIsNotNone(record)
            self.assertEqual(record["gate_id"], sfw.START_FRAME_GATE_ID)
            self.assertEqual(record["accepted_blockers"], BLOCKERS)
            partial = _order(tmp, detectors=sfw.blocker_detectors(UNIT, BLOCKERS[:2]), sha=sha, seq=12)
            self.assertIsNone(sfw.start_frame_acceptance("E02", UNIT, BLOCKERS, sha, [partial], "owner-1"))
            self.assertIsNone(sfw.start_frame_acceptance("E02", UNIT, BLOCKERS, "d" * 64, [full], "owner-1"))
            changed = BLOCKERS + ["KEYFRAME_CHANGED_SINCE_REVIEW"]
            order = _order(tmp, detectors=sfw.blocker_detectors(UNIT, changed), sha=sha, seq=13)
            self.assertIsNone(sfw.start_frame_acceptance("E02", UNIT, changed, sha, [order], "owner-1"))
            self.assertIsNone(sfw.start_frame_acceptance("E02", UNIT, BLOCKERS, sha, [], "owner-1"))


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        img = root / "tail.png"
        img.write_bytes(b"tail-frame")
        self.sha = hashlib.sha256(img.read_bytes()).hexdigest()
        self.ref = {"path": str(img), "sha256": self.sha}
        self.spec = {"cast": [{"character": "陆九"}, {"character": "沈青"}], "props": [{"prop": "茶壶"}]}
        self.anchors = ["LOC-YAOPU-INT", "SUB-1"]
        record = {"schema": "qingshan.line_owner_gate_acceptance.v2", "episode": "E02",
                  "gate_id": sfw.START_FRAME_GATE_ID, "gate_status_kept": "FAIL",
                  "accepted_detectors": sfw.blocker_detectors(UNIT, BLOCKERS), "order_seq": 11,
                  "media_item_id": UNIT, "media_sha256": self.sha, "media_sha256_bound_by_order": self.sha,
                  "self_issued": False}
        self.evidence = {"status": "ACCEPTED_BY_LINE_OWNER_ORDER", "reference_path": str(img),
                         "reference_sha256": self.sha, "observed_visible_characters": ["陆九"],
                         "observed_visible_props": [], "observed_space_anchors": self.anchors,
                         "camera_start_framing_match": True, "space_match": True,
                         "empty_establishing_frame": False, "line_owner_acceptance": record}
        self.write_evidence(self.evidence)
        self.contract = {"status": "ACCEPTED_BY_LINE_OWNER_ORDER", "reference_path": str(img),
                         "reference_sha256": self.sha, "evidence_ref": "ev.json",
                         "observed_visible_characters": ["陆九"], "observed_visible_props": [],
                         "observed_space_anchors": self.anchors, "camera_start_framing_match": True,
                         "space_match": True, "empty_establishing_frame": False,
                         "line_owner_acceptance": deepcopy(record)}

    def tearDown(self):
        self.tmp.cleanup()

    def write_evidence(self, payload):
        (self.root / "ev.json").write_text(json.dumps(payload, ensure_ascii=False))

    def validate(self, contract):
        return validate_start_anchor_semantics(contract, unit_id=UNIT, first_reference=self.ref,
                                               first_prompt_spec=self.spec, camera_plan={},
                                               required_space_anchors=self.anchors, root=self.root)

    def test_accepted_gaps_are_waived_and_observations_stay_honest(self):
        out = self.validate(deepcopy(self.contract))
        self.assertEqual(out["observed_visible_characters"], ["陆九"])  # 沈青 is not claimed as observed
        self.assertEqual(out["status"], "ACCEPTED_BY_LINE_OWNER_ORDER")

    def test_gap_not_named_by_the_order_still_fails(self):
        spec = deepcopy(self.spec)
        spec["props"].append({"prop": "油灯"})
        with self.assertRaises(ValueError):
            validate_start_anchor_semantics(deepcopy(self.contract), unit_id=UNIT, first_reference=self.ref,
                                            first_prompt_spec=spec, camera_plan={},
                                            required_space_anchors=self.anchors, root=self.root)

    def test_record_must_be_bound_unforged_and_match_evidence(self):
        for mutate in (lambda r: r.update(media_sha256="e" * 64), lambda r: r.update(self_issued=True),
                       lambda r: r.update(gate_id="CHARACTER-IDENTITY-ADMISSION"),
                       lambda r: r.update(media_item_id="E02-VU-002")):
            contract = deepcopy(self.contract)
            mutate(contract["line_owner_acceptance"])
            with self.assertRaises(ValueError):
                self.validate(contract)
        evidence = deepcopy(self.evidence)
        evidence["line_owner_acceptance"]["order_seq"] = 99
        self.write_evidence(evidence)
        with self.assertRaises(ValueError):
            self.validate(deepcopy(self.contract))

    def test_pass_contract_is_unchanged(self):
        contract = deepcopy(self.contract)
        contract.pop("line_owner_acceptance")
        contract["status"] = "PASS"
        evidence = deepcopy(self.evidence)
        evidence["status"] = "PASS"
        evidence.pop("line_owner_acceptance")
        self.write_evidence(evidence)
        with self.assertRaises(ValueError):  # a PASS receipt may not hide a missing character
            self.validate(contract)


class ActionRoleAcceptanceTests(unittest.TestCase):
    """E02-VU-004 (2026-10-14): the derived start frame shows neither the action's owner nor the prop."""

    AR_BLOCKERS = ["VLM_REVIEW_REJECT", "INITIATOR_IS_EXPECTED_ENTITY_NOT_PASS", "PROP_OWNERSHIP_AS_EXPECTED_NOT_PASS"]

    def test_writer_accepts_only_a_full_sha_bound_order(self):
        sha = "f" * 64
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            full = _order(tmp, detectors=sfw.blocker_detectors(UNIT, self.AR_BLOCKERS), sha=sha,
                          gate=arw.ACTION_ROLE_GATE_ID)
            record = arw.action_role_acceptance("E02", UNIT, self.AR_BLOCKERS, sha, [full], "owner-1")
            self.assertEqual(record["gate_id"], arw.ACTION_ROLE_GATE_ID)
            # a start-frame order never covers the action-role gate
            sf = _order(tmp, detectors=sfw.blocker_detectors(UNIT, self.AR_BLOCKERS), sha=sha, seq=12)
            self.assertIsNone(arw.action_role_acceptance("E02", UNIT, self.AR_BLOCKERS, sha, [sf], "owner-1"))
            bad = self.AR_BLOCKERS + ["CONTRACT_INITIATOR_OR_TARGET_UNDECLARED"]
            o = _order(tmp, detectors=sfw.blocker_detectors(UNIT, bad), sha=sha, seq=13, gate=arw.ACTION_ROLE_GATE_ID)
            self.assertIsNone(arw.action_role_acceptance("E02", UNIT, bad, sha, [o], "owner-1"))

    def payload(self, sha, **record_overrides):
        record = {"gate_id": arw.ACTION_ROLE_GATE_ID, "gate_status_kept": "FAIL", "order_seq": 12,
                  "media_item_id": UNIT, "media_sha256": sha, "media_sha256_bound_by_order": sha,
                  "self_issued": False, "accepted_detectors": sfw.blocker_detectors(UNIT, self.AR_BLOCKERS)}
        record.update(record_overrides)
        return {"schema": "qingshan.action_role_verification.v1", "unit_id": UNIT,
                "status": "ACCEPTED_BY_LINE_OWNER_ORDER", "reviewed_asset_sha256": sha,
                "interaction_state": "BRIDGE_STATE_NO_ACTION_OWNER_VISIBLE", "initiator_entity_id": "CHAR-SHENQING",
                "target_entity_id": "PROP-TEAPOT", "forbidden_role_reversal": True, "prop_ownership": [],
                "blockers": self.AR_BLOCKERS, "line_owner_acceptance": record}

    def test_gate_accepts_bound_record_and_refuses_forged_or_unbound(self):
        import tools.shot_media_admission_gate as gate
        sha = "f" * 64
        good = self.payload(sha)
        good["schema"] = gate.ACTION_ROLE_VERIFICATION_SCHEMA
        self.assertEqual(_validate_action_role_verification(good, expected_sha=sha), [])
        for overrides in ({"media_sha256": "0" * 64}, {"self_issued": True}, {"gate_id": sfw.START_FRAME_GATE_ID}):
            bad = self.payload(sha, **overrides)
            bad["schema"] = gate.ACTION_ROLE_VERIFICATION_SCHEMA
            self.assertIn("Q1_ACTION_ROLE_VERIFICATION_INVALID", _validate_action_role_verification(bad, expected_sha=sha))
        failing = self.payload(sha)
        failing["schema"] = gate.ACTION_ROLE_VERIFICATION_SCHEMA
        failing["status"] = "FAIL"
        self.assertIn("Q1_ACTION_ROLE_VERIFICATION_INVALID", _validate_action_role_verification(failing, expected_sha=sha))


if __name__ == "__main__":
    unittest.main()
