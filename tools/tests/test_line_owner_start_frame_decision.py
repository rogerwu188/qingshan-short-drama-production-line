"""A line-owner decision lets a continuity-derived unit open on its own keyframe on any episode (2026-10-29):
the derived tail copy is parked, S5 treats the keyframe as missing, the builder keeps the tail off the
references.  Automatic (measured) rows stay CAMERA_GRAMMAR_V1-only."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
sys.path.insert(0, str(ROOT))

import nalu_pipeline as npl  # noqa: E402
from tools.tests.test_camera_grammar_start_frames import LEGACY, STAMPED, PipelineFixture  # noqa: E402

AUTHORITY = "line owner 2026-10-29: option b, composition redesign"


class LineOwnerDecisionTest(unittest.TestCase):
    def test_legacy_episode_decision_parks_derived_copy_and_requires_own_keyframe(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), LEGACY) as fx:
            fx.kf2.write_bytes(b"derived copy of the tail")
            sidecar = fx.kf2.with_name(fx.kf2.name.replace(".png", ".derived.json"))
            sidecar.write_text(json.dumps({"source_sha256": "x"}))
            row = npl.record_line_owner_start_frame_decision(fx.ctx, "E03-VU-002", authority=AUTHORITY,
                                                             reason="SECOND_FACE_AT_FRAME_EDGE")
            self.assertEqual(row["decided_by"], "LINE_OWNER")
            self.assertEqual(row["start_frame_source"], npl.START_FRAME_OWN)
            self.assertEqual(row["previous_unit_id"], "E03-VU-001")
            self.assertFalse(fx.kf2.exists(), "the derived copy is parked, not deleted")
            self.assertTrue(Path(row["parked_derived_keyframe"]).is_file())
            self.assertTrue(Path(row["parked_derived_sidecar"]).is_file())
            self.assertEqual(fx.decisions()["E03-VU-002"]["authority"], AUTHORITY)
            # the next materialisation does not copy the tail back
            rows = npl.materialise_derived_keyframes(fx.ctx)
            self.assertEqual([r["status"] for r in rows], ["OWN_KEYFRAME_REQUIRED"])
            self.assertFalse(fx.kf2.exists())
            # S5 lists the own keyframe prompt as missing
            self.assertIn("E03-S01-02-KEYFRAME-V1.txt", npl.s5_keyframes_missing(fx.ctx))

    def test_legacy_episode_ignores_automatic_rows_but_honours_line_owner_rows(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), LEGACY) as fx:
            npl.record_start_frame_source(fx.ctx, "E03-VU-002", {"start_frame_source": npl.START_FRAME_OWN,
                                                                 "reason": "TAIL_REJECTED"})
            rows = npl.materialise_derived_keyframes(fx.ctx)
            self.assertNotEqual(rows[0]["status"], "OWN_KEYFRAME_REQUIRED")
            self.assertTrue(fx.kf2.exists(), "a measured row never applies to a legacy episode")
            import build_nalu_preproduction as bnp
            self.assertEqual(bnp.tail_rejected_start_frame_units(fx.ctx.p.preprod, "E03", LEGACY), set())
            fx.kf2.unlink()
            npl.record_start_frame_source(fx.ctx, "E03-VU-002", {"start_frame_source": npl.START_FRAME_OWN,
                                                                 "decided_by": "LINE_OWNER", "reason": "REDESIGN",
                                                                 "authority": AUTHORITY})
            self.assertEqual(bnp.tail_rejected_start_frame_units(fx.ctx.p.preprod, "E03", LEGACY), {"E03-VU-002"})
            self.assertEqual(bnp.tail_rejected_start_frame_units(fx.ctx.p.preprod, "E03", STAMPED), {"E03-VU-002"})

    def test_decision_refuses_non_derived_unit_clip_on_disk_and_missing_authority(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), LEGACY) as fx:
            with self.assertRaises(SystemExit):
                npl.record_line_owner_start_frame_decision(fx.ctx, "E03-VU-001", authority=AUTHORITY, reason="x")
            with self.assertRaises(SystemExit):
                npl.record_line_owner_start_frame_decision(fx.ctx, "E03-VU-002", authority="", reason="x")
            (fx.ctx.p.video_media / "E03-VU-002.mp4").write_bytes(b"clip")
            with self.assertRaises(SystemExit):
                npl.record_line_owner_start_frame_decision(fx.ctx, "E03-VU-002", authority=AUTHORITY, reason="x")
            self.assertEqual(fx.decisions(), {})

    def test_cli_subcommand_registered(self):
        src = (ROOT / "lines" / "nalu" / "runtime" / "tools" / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('subs.add_parser("start-frame-decision"', src)
        self.assertIn("func=cmd_start_frame_decision", src)


if __name__ == "__main__":
    unittest.main()
