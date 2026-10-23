"""Dialogue sound bridge / L-cut (CAMERA_GRAMMAR_V1, line owner 2026-10-23): a silent reaction shot may
let the previous line play on over its picture; absent field / unstamped episodes assemble as before."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import build_burnin_subtitles as subs  # noqa: E402
import dialogue_sound_bridge as bridge  # noqa: E402
from tools.build_agentcut_from_admitted_storyboard_sources import build  # noqa: E402


def contract(bridge_seconds=1.0, *, reaction_line=False, stamped=True):
    shots = [{"shot_id": "S1", "target_seconds": 4.0},
             {"shot_id": "S2", "target_seconds": 3.0, "prompt_spec": {}}]
    if bridge_seconds is not None:
        shots[1]["prompt_spec"]["transition"] = {"sound_bridge_from_previous_seconds": bridge_seconds}
    lines = [{"shot_id": "S1", "speaker_id": "CHAR-A", "text": "You knew all along."}]
    if reaction_line:
        lines.append({"shot_id": "S2", "speaker_id": "CHAR-A", "text": "Say it."})
    body = {"episode": "E99", "dialogue_language": "en",
            "character_entities": [{"character_id": "CHAR-A", "canonical_name": "A",
                                    "identity_source": {"mode": "TEXT_TO_IMAGE"}}],
            "shots": shots,
            "audio_contract": {"bgm": "NONE_WHOLE_EPISODE", "native_dialogue_only": True, "dialogue_units": lines}}
    if stamped:
        body["camera_grammar_policy"] = "CAMERA_GRAMMAR_V1"
    return body


GROUPING = {"units": [{"unit_id": "E99-VU-001", "editorial_shot_ids": ["S1"]},
                      {"unit_id": "E99-VU-002", "editorial_shot_ids": ["S2"]}]}
ASR = {"E99-VU-001": [{"start": 0.3, "end": 1.2, "text": "You knew"}, {"start": 1.4, "end": 2.6, "text": "all along."}]}


class PlanTests(unittest.TestCase):
    def test_requested_seconds_clamped_to_range(self):
        self.assertEqual(bridge.requested_seconds(contract(0.1)["shots"][1]), 0.3)
        self.assertEqual(bridge.requested_seconds(contract(5)["shots"][1]), 2.0)
        self.assertEqual(bridge.requested_seconds(contract("0.8")["shots"][1]), 0.8)
        self.assertIsNone(bridge.requested_seconds(contract(None)["shots"][1]))
        self.assertIsNone(bridge.requested_seconds(contract("soon")["shots"][1]))

    def test_plan_requests_bridge_with_line_start(self):
        row = bridge.plan(contract(1.0), GROUPING, ASR)["rows"][0]
        self.assertEqual(row["status"], "REQUESTED")
        self.assertEqual((row["from_unit_id"], row["to_unit_id"]), ("E99-VU-001", "E99-VU-002"))
        self.assertEqual(row["line_start_seconds"], 1.4)

    def test_plan_skips_unusable_requests(self):
        self.assertEqual(bridge.plan(contract(1.0, reaction_line=True), GROUPING, ASR)["rows"][0]["reason"],
                         "REACTION_SHOT_HAS_DIALOGUE")
        one_unit = {"units": [{"unit_id": "E99-VU-001", "editorial_shot_ids": ["S1", "S2"]}]}
        self.assertEqual(bridge.plan(contract(1.0), one_unit, ASR)["rows"][0]["reason"], "NOT_AT_UNIT_BOUNDARY")
        self.assertEqual(bridge.plan(contract(1.0), GROUPING, {})["rows"][0]["reason"], "SPEAKER_LINE_START_UNKNOWN")
        self.assertEqual(bridge.plan(contract(None), GROUPING, ASR)["rows"], [])


class TimingTests(unittest.TestCase):
    def test_bridge_never_cuts_before_line_start(self):
        # speaker clip 0..3.1 s, line starts at 2.4 -> at most 0.7 s of bridge
        self.assertAlmostEqual(bridge.bridge_seconds(2.0, 0.0, 3.1, 2.4, 5.0), 0.7)

    def test_reaction_outlasts_bridge(self):
        self.assertAlmostEqual(bridge.bridge_seconds(1.5, 0.0, 4.0, 0.5, 1.6), 1.1)

    def test_tiny_bridge_after_clamp_is_dropped(self):
        self.assertEqual(bridge.bridge_seconds(1.0, 0.0, 3.0, 2.95, 5.0), 0.0)

    def test_apply_shortens_speaker_and_restacks(self):
        video = [{"start": 0.0, "in": 0.0, "duration": 3.1, "source": "a.mp4", "metadata": {"source_id": "U1"}},
                 {"start": 3.1, "in": 0.0, "duration": 3.0, "source": "b.mp4", "metadata": {"source_id": "U2"}},
                 {"start": 6.1, "in": 0.0, "duration": 2.0, "source": "c.mp4", "metadata": {"source_id": "U3"}}]
        audio = [dict(v, metadata=dict(v["metadata"]), volume=0.78) for v in video]
        report = {"rows": [{"status": "REQUESTED", "from_unit_id": "U1", "to_unit_id": "U2",
                            "requested_seconds": 1.0, "line_start_seconds": 1.0}]}
        rows = bridge.apply(video, audio, report)
        self.assertEqual(rows[0]["status"], "APPLIED")
        self.assertEqual([c["duration"] for c in video], [2.1, 3.0, 2.0])
        self.assertEqual([c["start"] for c in audio], [0.0, 2.1, 5.1])
        self.assertEqual((rows[0]["picture_cut_seconds"], rows[0]["bridge_end_seconds"]), (2.1, 3.1))
        self.assertEqual(rows[0]["audio_in"], 2.1)
        self.assertEqual(video[0]["metadata"]["sound_bridge_out"]["seconds"], 1.0)
        self.assertEqual(audio[1]["metadata"]["sound_bridge_in"]["speaker_unit_id"], "U1")

    def test_mix_filter_relays_speaker_audio_and_ducks_native(self):
        f = bridge.mix_filter([{"picture_cut_seconds": 2.1, "bridge_end_seconds": 3.1, "applied_seconds": 1.0,
                                "audio_in": 2.1, "volume": 0.78}])
        self.assertIn("atrim=start=2.100000:duration=1.000000", f)
        self.assertIn("adelay=2100|2100", f)
        self.assertIn("0.125893", f)  # -18 dB
        self.assertIn("amix=inputs=2:duration=first:normalize=0[aout]", f)


class SubtitleTests(unittest.TestCase):
    def test_caption_follows_speech_over_reaction_picture(self):
        clip = {"start": 0.0, "in": 0.0, "duration": 2.1}
        # the line runs 1.4-2.6 s of the speaker source; picture cut at 2.1 s
        self.assertAlmostEqual(subs.caption_window(clip, 1.4, 2.6, 0.08)[1], 2.1)  # cut with the picture
        s, e = subs.caption_window(clip, 1.4, 2.6, 0.08, bridge_seconds=1.0)
        self.assertAlmostEqual(s, 1.32)
        self.assertAlmostEqual(e, 2.68)


class BuildTests(unittest.TestCase):
    def _build(self, root, tag, **kwargs):
        clips = []
        for name in ("E99-VU-001", "E99-VU-002"):
            path = root / f"{name}.mp4"
            path.write_bytes(name.encode())
            clips.append(path)
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({"tasks": [
            {"source_id": "E99-VU-001", "status": "qa_pass", "output_path": str(clips[0]), "duration": 3.1},
            {"source_id": "E99-VU-002", "status": "qa_pass", "output_path": str(clips[1]), "duration": 3.0}]}))
        review = root / "review.json"
        review.write_text(json.dumps({"passed_items": [{"path": str(p)} for p in clips]}))
        gc = root / "gc.json"
        gc.write_text(json.dumps(contract(None, stamped=False)))
        project = root / f"project_{tag}.json"
        build("E99", [receipt], review, project, root / f"adm_{tag}.json", root / "out.mp4", 2, gc, **kwargs)
        return project

    def test_bridge_applied_in_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "bridge.json"
            report.write_text(json.dumps(bridge.plan(contract(1.0), GROUPING, ASR)))
            payload = json.loads(self._build(root, "b", dialogue_sound_bridge=report).read_text())
            video = payload["timeline"]["videoTracks"][0]["clips"]
            audio = payload["timeline"]["audioTracks"][0]["clips"]
            self.assertEqual([c["duration"] for c in video], [2.1, 3.0])
            self.assertEqual([c["duration"] for c in audio], [2.1, 3.0])
            self.assertEqual([c["start"] for c in video], [0.0, 2.1])
            self.assertAlmostEqual(payload["metadata"]["runtime_seconds"], 5.1)
            applied = payload["metadata"]["dialogue_sound_bridge"]["bridges"]
            self.assertEqual(applied[0]["status"], "APPLIED")
            self.assertEqual(applied[0]["picture_cut_seconds"], 2.1)

    def test_without_bridge_project_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plain = self._build(root, "a").read_bytes()
            explicit_none = self._build(root, "b", dialogue_sound_bridge=None).read_bytes()
            self.assertEqual(plain.replace(b"adm_a", b"X").replace(b"project_a", b"X"),
                             explicit_none.replace(b"adm_b", b"X").replace(b"project_b", b"X"))
            self.assertNotIn(b"sound_bridge", plain)


class PipelineTests(unittest.TestCase):
    def test_unstamped_or_absent_field_writes_nothing(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = root / "grouping.json"
            g.write_text(json.dumps(GROUPING))
            ctx = mock.Mock(episode="E99")
            ctx.p = mock.Mock(assembly=root / "assembly", grouping_plan=g)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            self.assertIsNone(nalu_pipeline.s7_dialogue_sound_bridge(ctx, res, contract(1.0, stamped=False), None))
            self.assertIsNone(nalu_pipeline.s7_dialogue_sound_bridge(ctx, res, contract(None), ASR))
            self.assertNotIn("dialogue_sound_bridge", res.details)
            self.assertFalse((root / "assembly").exists())
            path = nalu_pipeline.s7_dialogue_sound_bridge(ctx, res, contract(1.0), ASR)
            self.assertEqual(path, root / "assembly" / "E99_DIALOGUE_SOUND_BRIDGE.json")
            self.assertEqual(res.details["dialogue_sound_bridge"]["requested"], 1)

    def test_mix_is_noop_without_applied_bridges(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project.json"
            project.write_text(json.dumps({"metadata": {}}))
            ctx = mock.Mock(episode="E99")
            ctx.p = mock.Mock(agentcut_project=project, assembly=root)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            picture = root / "p.mp4"
            self.assertEqual(nalu_pipeline.s7_sound_bridge_mix(ctx, res, picture), (picture, []))
            self.assertNotIn("dialogue_sound_bridge", res.details)


if __name__ == "__main__":
    unittest.main()
