"""S7 honours the same RELEASE-AUDIO-LOUDNESS order the read-only helper matches (device 1101 E18, 2026-11-20).

The helper (roger_gate_acceptance.find_acceptance) matched seq=531; the runner refused it because (a) it read no
orders at all whenever the PAID order was refused (ctx.authority_blockers), and (b) it looked for the sha only
under media_sha256_by_item["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE"].  These tests drive the real S7 lookup."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402

OWNER = "Roger"
FAILING = ["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:-21.4:DIALOGUE",
           "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-007:-14.9:AMBIENCE",
           "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:VU-006->VU-007:8.6LU"]


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.assembly = root / "assembly"
        self.assembly.mkdir()
        self.levelled = self.assembly / "E18_final_levelled_9x16.mp4"
        self.levelled.write_bytes(b"levelled-v2")
        self.report = self.assembly / "E18_NATIVE_AUDIO_LOUDNESS.json"
        self.sha = hashlib.sha256(b"levelled-v2").hexdigest()
        self.write_report(self.report, self.sha, FAILING, picture="pic-1")
        self.p = SimpleNamespace(final_levelled=self.levelled, leveled_audio_report=self.report,
                                 assembly=self.assembly)
        self.orders_path = root / "private" / "SUPERVISOR_ORDERS.json"
        self.orders_path.parent.mkdir()
        self.rows: list[dict] = []

    @staticmethod
    def write_report(path: Path, sha: str, failures: list[str], *, picture: str) -> None:
        path.write_text(json.dumps({"status": "FAIL", "failures": failures, "output_release": {"sha256": sha},
                                    "source_video_stream_sha256": picture}), encoding="utf-8")

    def add_order(self, *, seq: int = 531, gate_id: str = "RELEASE-AUDIO-LOUDNESS", detectors=FAILING,
                  binding: dict | None = None, episode: str = "E18") -> None:
        verbatim = "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）"
        order_id = f"ROGER-E18-{seq}"
        receipt = self.orders_path.parent / f"receipt_{seq}.json"
        receipt.write_text(json.dumps({"schema": "qingshan.line_owner_order_source_receipt.v1",
                                       "status": "CONFIRMED", "issued_by": OWNER, "order_seq": seq,
                                       "order_id": order_id, "verbatim": verbatim,
                                       "recorded_at_utc": "2026-11-20T00:00:00Z"}), encoding="utf-8")
        decision = {"kind": "GATE_FAIL_ACCEPTANCE", "episode": episode, "gate_id": gate_id,
                    "detectors": sorted(detectors)}
        decision.update(binding if binding is not None else {"media_sha256": self.sha})
        self.rows.append({"seq": seq, "id": order_id, "issued_by": OWNER, "status": "active", "order": verbatim,
                          "decision": decision,
                          "source_receipt": {"path": str(receipt),
                                             "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}})
        self.orders_path.write_text(json.dumps({"_schema": "supervisor_orders_v1",
                                                "latest_order_seq": max(r["seq"] for r in self.rows),
                                                "orders": self.rows}), encoding="utf-8")

    def ctx(self, *, blockers=("EPISODE_OUT_OF_ORDER_SCOPE:E18",), owner: str | None = OWNER):
        latest = max((r["seq"] for r in self.rows), default=1)
        return SimpleNamespace(episode="E18", authority={"orders_path": self.orders_path, "line_owner_id": owner,
                                                          "latest_order_seq": latest},
                               authority_blockers=list(blockers))

    def lookup(self, failing=FAILING, **ctx_kw):
        return npl.s7_release_loudness_acceptance(self.ctx(**ctx_kw), self.p, list(failing), self.sha)


class S7LoudnessAcceptanceTest(unittest.TestCase):
    def test_runner_adopts_the_order_the_helper_matches_despite_a_paid_order_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order()   # plain decision.media_sha256, as the helper is called without media_item_id
            helper = npl._rga.find_acceptance(fx.rows, episode="E18", gate_id="RELEASE-AUDIO-LOUDNESS",
                                              failing=FAILING, media_sha256=fx.sha, expected_issuer=OWNER)
            self.assertIsNotNone(helper)
            order, info = fx.lookup()
            self.assertEqual(order["seq"], 531)
            self.assertEqual(info["rule"], "EXACT_SHA")
            self.assertIsNone(info["media_item_id"])
            record = npl._rga.acceptance_record(order, episode="E18", gate_id="RELEASE-AUDIO-LOUDNESS",
                                                failing=FAILING, media_sha256=fx.sha,
                                                media_item_id=info["media_item_id"], gate_result_path="r")
            self.assertEqual(record["gate_status_kept"], "FAIL")

    def test_historical_and_recorder_binding_keys_are_honoured(self):
        for key in ("UNIT_LOUDNESS_OUT_OF_ROLE_RANGE", "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED",
                    "RELEASE-AUDIO-LOUDNESS", "final_levelled"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as d:
                fx = Fixture(Path(d))
                fx.add_order(binding={"media_sha256_by_item": {key: fx.sha}})
                order, info = fx.lookup()
                self.assertIsNotNone(order)
                self.assertEqual(info["media_item_id"], key)

    def test_non_matching_orders_still_fail(self):
        cases = {
            "missing_failure": dict(detectors=FAILING[:2]),
            "wrong_sha": dict(binding={"media_sha256": "f" * 64}),
            "other_episode": dict(episode="E17"),
            "other_gate": dict(gate_id="FINAL-CUT-CAMERA-MOTION"),
            "no_binding": dict(binding={}),
        }
        for name, kw in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                fx = Fixture(Path(d))
                fx.add_order(**kw)
                order, info = fx.lookup()
                self.assertIsNone(order)
                self.assertEqual(info["reason"], "NO_ORDER_MATCHES_EPISODE_GATE_FAILURES_AND_SHA")

    def test_no_line_owner_reads_no_orders(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order()
            order, info = fx.lookup(owner=None)
            self.assertIsNone(order)
            self.assertEqual(info["orders_read"], 0)

    def test_gate_id_spellings_are_normalised(self):
        for gate in ("RELEASE_AUDIO_LOUDNESS", "release-audio-loudness", "RELEASE_AUDIO_LEVELLING_FAILED"):
            with self.subTest(gate=gate), tempfile.TemporaryDirectory() as d:
                fx = Fixture(Path(d))
                fx.add_order(gate_id=gate)
                self.assertIsNotNone(fx.lookup()[0])
        self.assertEqual(npl._rga.normalize_gate_id("final_cut_camera_motion_fail"), "FINAL-CUT-CAMERA-MOTION")

    def test_rerun_relevel_of_same_picture_keeps_the_order(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            old_sha = hashlib.sha256(b"levelled-v1").hexdigest()
            parked = fx.assembly / "E18_NATIVE_AUDIO_LOUDNESS__superseded_0123456789ab.json"
            old_failing = ["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:-21.2:DIALOGUE",
                           "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-007:-15.1:AMBIENCE",
                           "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:VU-006->VU-007:8.3LU"]
            fx.write_report(parked, old_sha, old_failing, picture="pic-1")
            fx.add_order(detectors=old_failing, binding={"media_sha256": old_sha})
            order, info = fx.lookup()
            self.assertEqual(order["seq"], 531)
            self.assertEqual(info["rule"], "RECORDED_DRIFT_SAME_PICTURE")
            self.assertEqual(info["bound_sha256"], old_sha)
            # a different picture is a different cut: no carry-over
            fx.write_report(parked, old_sha, old_failing, picture="pic-OTHER")
            self.assertIsNone(fx.lookup()[0])
            # a NEW failing unit on the same picture is not covered either
            fx.write_report(parked, old_sha, old_failing, picture="pic-1")
            self.assertIsNone(fx.lookup(failing=FAILING + ["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-009:-30.0:MUSIC"])[0])

    def test_failure_identity_strips_only_measured_values(self):
        self.assertEqual(npl._loudness_failure_identity("UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:-21.4:DIALOGUE"),
                         "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:DIALOGUE")
        self.assertEqual(npl._loudness_failure_identity("ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:VU-1->VU-2:8.6LU"),
                         "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:VU-1->VU-2")
        self.assertEqual(npl._loudness_failure_identity("RELEASE_TRUE_PEAK_EXCEEDS_CEILING:-0.4"),
                         "RELEASE_TRUE_PEAK_EXCEEDS_CEILING")


if __name__ == "__main__":
    unittest.main()
