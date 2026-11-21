"""S7 RELEASE-AUDIO-LOUDNESS acceptance, second pass (device 1101 E19, 2026-11-21).

Orders seq 551/552 bound the current levelled file's sha, yet S7 kept returning RELEASE_AUDIO_LEVELLING_FAILED:
the runner demanded every failure VERBATIM in ``decision.detectors`` (recording agents use the ``<unit>:<blocker>``
shape of every other gate, the bare failure code, or numbers copied from an earlier report), and a trailing
NALU_LATEST_ORDER_SEQ behind a paid row blanked the whole inbox for every gate.  The lookup now names, per order,
the check that refused it."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_nalu_s7_loudness_acceptance_honored import FAILING, OWNER, Fixture, npl  # noqa: E402


def _paid_row(fx: Fixture, seq: int) -> None:
    fx.rows.append({"seq": seq, "id": f"ROGER-PAID-{seq}", "issued_by": OWNER, "status": "active",
                    "order": "S6 redo", "decision": {"kind": "PAID_PRODUCTION", "paid_requests_allowed": True}})
    fx.orders_path.write_text(json.dumps({"_schema": "supervisor_orders_v1",
                                          "latest_order_seq": max(r["seq"] for r in fx.rows),
                                          "orders": fx.rows}), encoding="utf-8")


class DetectorShapesOnExactSha(unittest.TestCase):
    def test_every_recording_shape_is_honoured_on_the_exact_file(self):
        shapes = {
            "unit_first": ["VU-003:UNIT_LOUDNESS_OUT_OF_ROLE_RANGE", "VU-007:UNIT_LOUDNESS_OUT_OF_ROLE_RANGE",
                           "VU-007:ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED"],
            "bare_codes": ["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE", "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED"],
            "older_numbers": ["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:-21.1:DIALOGUE",
                              "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-007:-15.2:AMBIENCE",
                              "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:VU-006->VU-007:8.2LU"],
            "blocker_name": ["RELEASE_AUDIO_LEVELLING_FAILED"],
            "gate_id": ["RELEASE-AUDIO-LOUDNESS"],
        }
        for name, detectors in shapes.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                fx = Fixture(Path(d))
                fx.add_order(seq=551, detectors=detectors,
                             binding={"media_sha256_by_item": {d.split(":")[0]: fx.sha for d in detectors}})
                order, info = fx.lookup()
                self.assertIsNotNone(order, info)
                self.assertEqual(info["rule"], "EXACT_SHA")
                self.assertEqual(info["coverage"], "BY_IDENTITY_OR_CODE")
                record = npl._rga.acceptance_record(order, episode="E18", gate_id=npl.RELEASE_LOUDNESS_GATE_ID,
                                                    failing=FAILING, media_sha256=fx.sha,
                                                    media_item_id=info["media_item_id"], gate_result_path="r")
                self.assertEqual(record["media_sha256"], fx.sha)

    def test_any_binding_key_holding_the_exact_sha_counts(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order(seq=551, binding={"media_sha256_by_item": {"E18_final_levelled_9x16": fx.sha}})
            order, info = fx.lookup()
            self.assertEqual(order["seq"], 551)
            self.assertEqual(info["media_item_id"], "E18_final_levelled_9x16")

    def test_duplicate_failure_rows_do_not_defeat_the_order(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order(seq=551)
            self.assertIsNotNone(fx.lookup(failing=FAILING + FAILING[:1])[0])

    def test_shapes_still_refuse_an_uncovered_unit_or_code_and_a_wrong_sha(self):
        cases = {
            "other_unit": dict(detectors=["VU-003:UNIT_LOUDNESS_OUT_OF_ROLE_RANGE",
                                          "VU-007:ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED"]),
            "missing_code": dict(detectors=["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE"]),
            "other_role": dict(detectors=["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:MUSIC",
                                          "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-007:AMBIENCE",
                                          "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED"]),
            "blanket_wrong_sha": dict(detectors=["RELEASE-AUDIO-LOUDNESS"], binding={"media_sha256": "e" * 64}),
        }
        for name, kw in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                fx = Fixture(Path(d))
                fx.add_order(seq=551, **kw)
                self.assertIsNone(fx.lookup()[0])


class InboxAcknowledgement(unittest.TestCase):
    def test_paid_row_ahead_of_the_acknowledged_seq_no_longer_blanks_the_inbox(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order(seq=550)
            _paid_row(fx, 551)          # needs a manual acknowledgement for SPENDING
            fx.add_order(seq=552)
            ctx = fx.ctx()
            ctx.authority["latest_order_seq"] = 549
            order, info = npl.s7_release_loudness_acceptance(ctx, fx.p, list(FAILING), fx.sha)
            self.assertEqual(order["seq"], 552)
            self.assertEqual(info["inbox"]["inbox"], "ACK_TRAILS_INBOX_GATE_READ")
            self.assertEqual(info["inbox"]["ignored_unacknowledged_seqs"], [551])
            # the strict reader (paid path) still refuses the same inbox
            self.assertEqual(npl._rga._orders(fx.orders_path, expected_latest_seq=549, expected_issuer=OWNER), [])

    def test_structural_refusals_stay_total_and_are_named(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order(seq=551)
            ctx = fx.ctx()
            ctx.authority["latest_order_seq"] = 600
            order, info = npl.s7_release_loudness_acceptance(ctx, fx.p, list(FAILING), fx.sha)
            self.assertIsNone(order)
            self.assertEqual(info["orders_read"], 0)
            self.assertIn("BELOW_ACKNOWLEDGED_600", info["reason"])

    def test_unreceipted_newer_acceptance_is_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order(seq=551)
            fx.rows[-1]["source_receipt"]["sha256"] = "0" * 64
            fx.orders_path.write_text(json.dumps({"_schema": "supervisor_orders_v1", "latest_order_seq": 551,
                                                  "orders": fx.rows}), encoding="utf-8")
            ctx = fx.ctx()
            ctx.authority["latest_order_seq"] = 540
            order, info = npl.s7_release_loudness_acceptance(ctx, fx.p, list(FAILING), fx.sha)
            self.assertIsNone(order)
            self.assertEqual(info["inbox"]["ignored_unacknowledged_seqs"], [551])


class DriftOnRerun(unittest.TestCase):
    def _parked(self, fx: Fixture, *, where: str = "beside", picture: str = "pic-1") -> str:
        old_sha = hashlib.sha256(b"levelled-v1").hexdigest()
        old_failing = ["UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-003:-21.2:DIALOGUE",
                       "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-007:-15.1:AMBIENCE",
                       "ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED:VU-006->VU-007:8.3LU"]
        if where == "beside":
            path = fx.assembly / "E18_NATIVE_AUDIO_LOUDNESS__superseded_0123456789ab.json"
        else:                      # moved by hand, as the production doc says for the audience detectors
            folder = fx.assembly / "_superseded_20261121_loudness"
            folder.mkdir()
            path = folder / "E18_NATIVE_AUDIO_LOUDNESS.json"
        fx.write_report(path, old_sha, old_failing, picture=picture)
        return old_sha

    def test_relevel_drift_with_unit_first_detectors_is_carried(self):
        for where in ("beside", "hand_moved"):
            with self.subTest(where), tempfile.TemporaryDirectory() as d:
                fx = Fixture(Path(d))
                old_sha = self._parked(fx, where=where)
                fx.add_order(seq=552, detectors=["VU-003:UNIT_LOUDNESS_OUT_OF_ROLE_RANGE",
                                                 "VU-007:UNIT_LOUDNESS_OUT_OF_ROLE_RANGE",
                                                 "VU-007:ADJACENT_UNIT_LOUDNESS_DELTA_EXCEEDED"],
                             binding={"media_sha256_by_item": {"VU-003": old_sha, "VU-007": old_sha}})
                order, info = fx.lookup()
                self.assertEqual(order["seq"], 552, info)
                self.assertEqual(info["rule"], "RECORDED_DRIFT_SAME_PICTURE")
                self.assertEqual(info["bound_sha256"], old_sha)
                record = npl._rga.acceptance_record(order, episode="E18", gate_id=npl.RELEASE_LOUDNESS_GATE_ID,
                                                    failing=FAILING, media_sha256=old_sha,
                                                    media_item_id=info["media_item_id"], gate_result_path="r")
                self.assertEqual(record["media_sha256_bound_by_order"], old_sha)

    def test_drift_refuses_new_unit_and_other_picture_with_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            old_sha = self._parked(fx)
            fx.add_order(seq=552, detectors=["RELEASE-AUDIO-LOUDNESS"], binding={"media_sha256": old_sha})
            self.assertIsNotNone(fx.lookup()[0])
            extra = "UNIT_LOUDNESS_OUT_OF_ROLE_RANGE:VU-009:-30.0:MUSIC"
            order, info = fx.lookup(failing=FAILING + [extra])
            self.assertIsNone(order)
            drift = info["candidates"][0]["drift"][0]
            self.assertEqual(drift["refused"], "FAILURES_NOT_COVERED_ON_BOUND_FILE")
            self.assertEqual(drift["uncovered_failures"], [extra])
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            old_sha = self._parked(fx, picture="pic-OTHER")
            fx.add_order(seq=552, binding={"media_sha256": old_sha})
            order, info = fx.lookup()
            self.assertIsNone(order)
            self.assertEqual(info["candidates"][0]["drift"][0]["refused"], "DIFFERENT_PICTURE")


class Diagnostic(unittest.TestCase):
    def test_refusal_names_each_order_and_the_order_that_would_match(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            fx.add_order(seq=551, binding={"media_sha256": "a" * 64})
            fx.add_order(seq=552, detectors=FAILING[:1])
            fx.add_order(seq=553, episode="E17")
            order, info = fx.lookup()
            self.assertIsNone(order)
            self.assertEqual(info["reason"], "NO_ORDER_MATCHES_EPISODE_GATE_FAILURES_AND_SHA")
            by_seq = {c["seq"]: c for c in info["candidates"]}
            self.assertEqual(by_seq[551]["refused"], "SHA_NOT_CURRENT_AND_NOT_A_PARKED_LEVELLED_FILE_OF_THIS_EPISODE")
            self.assertFalse(by_seq[551]["binds_current_sha"])
            self.assertTrue(by_seq[552]["binds_current_sha"])
            self.assertEqual(by_seq[552]["uncovered_failures"], FAILING[1:])
            self.assertNotIn(553, by_seq)                      # other episode: not a candidate
            self.assertIn("--gate-id RELEASE-AUDIO-LOUDNESS", info["record_hint"])
            self.assertIn(f"--media UNIT_LOUDNESS_OUT_OF_ROLE_RANGE={fx.levelled}", info["record_hint"])

    def test_no_levelled_file_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            fx = Fixture(Path(d))
            order, info = npl.s7_release_loudness_acceptance(fx.ctx(), fx.p, list(FAILING), None)
            self.assertIsNone(order)
            self.assertTrue(info["reason"].startswith("NO_LEVELLED_FILE"))

    def test_stage_records_the_s7_path_and_reason_in_the_blocker_hint(self):
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("order, match = s7_release_loudness_acceptance(ctx, p, failing, final_sha)"):]
        body = body[:body.index("bound_sha = match.get")]
        for needle in ('match["s7_path"]', "REUSED_LEVELLED_FILE", "RELEVELLED", "FINAL_FIX_ROUND_S7_RERUN",
                       "match.get('reason')", 'res.blockers = ["RELEASE_AUDIO_LEVELLING_FAILED"]'):
            self.assertIn(needle, body)
        # one call site only: every S7 pass (first, final-fix rerun, re-entry) goes through the same lookup
        self.assertEqual(src.count("= s7_release_loudness_acceptance(ctx"), 1)
        self.assertEqual(src.count('"RELEASE_AUDIO_LEVELLING_FAILED"'), 1)


if __name__ == "__main__":
    unittest.main()
