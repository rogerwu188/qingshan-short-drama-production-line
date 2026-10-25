#!/usr/bin/env python3
"""V.O. narration (VOICE_ONLY_NO_PLATE speaker lines): S2 separation and window rule, S4 synthesis
(provider mocked, no network, no credits), S6 H3 no-speech units, S7 placement / mix / captions /
speaker map / BGM ducking, and the sha-bound admission of mixed-in narration.  Synthetic fixtures only."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:  # CI image has no Pillow; production installs it
    HAVE_PIL = False
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _path in (str(ROOT), str(NALU_TOOLS), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import voice_over_narration as vo  # noqa: E402
from tools import h3_crossmodal_speaker_gate as h3_gate  # noqa: E402
from tools import audio_postproduction_contract as apc  # noqa: E402
from tools import level_native_release_audio as leveller  # noqa: E402
from tools.character_entity_contract import validate_character_entity_contract  # noqa: E402

CURRENT = {"NALU_POLICY_PROFILE": "CURRENT_PORTABLE"}
LEGACY = {"NALU_POLICY_PROFILE": "LEGACY_EPISODE_COMPAT"}
LEDGER, ELIAS = "CHAR-LEDGER", "CHAR-ELIAS"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def entities(*, with_ledger: bool = True) -> list[dict]:
    rows = [{"character_id": ELIAS, "canonical_name": "Elias", "aliases": ["ELIAS"],
             "identity_source": {"mode": "LOCKED_PLATE"}}]
    if with_ledger:
        rows.append({"character_id": LEDGER, "canonical_name": "The Ledger", "aliases": ["LEDGER"],
                     "identity_source": {"mode": "VOICE_ONLY_NO_PLATE"}})
    return rows


def shot(sid: str, seconds: float, dialogue: str = "", cast: list[str] | None = None, *,
         speaker_id: str = "") -> dict:
    return {
        "shot_id": sid, "scene_id": "S1", "target_seconds": seconds,
        "shot_size": "MEDIUM", "camera": "TRACK", "axis": "A", "blocking": "Elias walks",
        "entry_state": "Elias stands at the door", "completion_state": "Elias reaches the desk",
        "prompt_spec": {
            "action": {"primary_action": "Elias walks to the desk"},
            "dialogue": dialogue,
            "cast": [{"character": "Elias", "character_id": ELIAS} for _ in (cast or [])],
            "role_semantic_disambiguation": ({"dialogue_speaker": "x", "dialogue_speaker_id": speaker_id,
                                              "lip_owner_id": ""} if speaker_id else {}),
        },
    }


def editorial_inputs(shots: list[dict], ents: list[dict]):
    contract = {"scene_states": [{"scene_id": "S1", "weather": "clear", "lighting": "cold white"}],
                "character_entities": ents, "non_character_entities": [], "shots": shots}
    plan_rows = [{"shot_id": s["shot_id"], "room_id": "ROOM-1", "zone_id": "Z1", "zone_ids": ["Z1"],
                  "angle_id": "ANG-1", "axis_id": "AX-1", "subspace_id": "SUB-1",
                  "global_space_map_id": "GSM-1", "prop_ids": []} for s in shots]
    index = SimpleNamespace(episode_map_id="EGSM-E01", rooms={"ROOM-1": {"name": "corridor"}},
                            zones={"Z1": {"name": "door"}}, elements=lambda _room: [])
    return contract, plan_rows, index


class EditorialBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.bnp = load("bnp_voice_over", NALU_TOOLS / "build_nalu_preproduction.py")
        except Exception as exc:  # noqa: BLE001 - the module needs the full engine tree
            raise unittest.SkipTest(f"build_nalu_preproduction not importable: {exc}")

    def build(self, shots: list[dict], ents: list[dict], *, env=CURRENT, language: str = "en"):
        contract, plan_rows, index = editorial_inputs(shots, ents)
        engine = SimpleNamespace(dialogue_limit=200, dialogue_length=len, language=language)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env, clear=False):
            root = Path(tmp)
            (root / "c.json").write_text("{}\n")
            (root / "g.json").write_text("{}\n")
            manifest, _ = self.bnp.build_editorial(contract, plan_rows, index, engine, "E01",
                                                   root / "c.json", root / "g.json", root)
        return manifest


class SeparationTests(EditorialBase):
    def test_voice_over_line_leaves_the_video_dialogue(self):
        manifest = self.build([
            shot("E01-S01-01", 2.0, "The Ledger：Subject: the Arbiter.", speaker_id=LEDGER),
            shot("E01-S01-02", 3.0, cast=[ELIAS]),
        ], entities())
        spec = manifest["shots"][0]["prompt_spec"]
        self.assertEqual(spec["dialogue"], "")
        self.assertEqual(spec["voice_over"], [{"line_index": 0, "speaker": "The Ledger",
                                               "character_id": LEDGER, "text": "Subject: the Arbiter."}])
        self.assertEqual(spec["audio_contract"], "DIEGETIC_OR_SILENT_NO_TTS")
        self.assertNotIn("dialogue_delivery", spec)
        self.assertNotIn(LEDGER, [row["character_id"] for row in spec["cast"]])
        role = spec["role_semantic_disambiguation"]
        self.assertEqual((role["dialogue_speaker_id"], role["lip_owner_id"]), ("", ""))
        self.assertEqual(manifest["voice_over_character_ids"], [LEDGER])
        self.assertNotIn("voice_over", manifest["shots"][1]["prompt_spec"])

    def test_authored_delivery_is_dropped_on_a_narration_only_shot(self):
        # Twelve Gazes E01 S2: a shot authored with dialogue_delivery whose only line is narration
        # kept the delivery and grouped_performance_contract rejected it (no dialogue left).
        narrated = shot("E01-S01-01", 6.0, "The Ledger：Subject: the Arbiter.", speaker_id=LEDGER)
        narrated["dialogue_delivery"] = {"words_per_second": 2.4}
        mixed = shot("E01-S01-02", 6.0, "Elias：Not yet.\nThe Ledger：Recorded.", cast=[ELIAS], speaker_id=ELIAS)
        mixed["dialogue_delivery"] = {"words_per_second": 2.4}
        manifest = self.build([narrated, mixed], entities())
        self.assertNotIn("dialogue_delivery", manifest["shots"][0]["prompt_spec"])
        self.assertEqual(manifest["shots"][1]["prompt_spec"]["dialogue_delivery"].get("words_per_second"), 2.4)

    def test_mixed_shot_keeps_the_on_screen_line_verbatim(self):
        manifest = self.build([shot("E01-S01-01", 6.0, "Elias：Not yet.\nThe Ledger：Recorded.",
                                    cast=[ELIAS], speaker_id=LEDGER)], entities())
        spec = manifest["shots"][0]["prompt_spec"]
        self.assertEqual(spec["dialogue"], "Elias：Not yet.")
        self.assertEqual(spec["voice_over"][0]["line_index"], 1)
        self.assertEqual(spec["audio_contract"], "SAME_VIDEO_TASK_NATIVE_AUDIO")
        role = spec["role_semantic_disambiguation"]
        self.assertEqual((role["dialogue_speaker_id"], role["lip_owner_id"]), (ELIAS, ELIAS))

    def test_contract_without_voice_over_speaker_is_unchanged(self):
        shots = [shot("E01-S01-01", 4.0, "秦铭：陆哥。", cast=[ELIAS])]
        shots[0]["prompt_spec"]["cast"] = [{"character": "秦铭", "character_id": "CHAR-QM"}]
        ents = [{"character_id": "CHAR-QM", "canonical_name": "秦铭", "aliases": []}]
        current = self.build(shots, ents, language="zh")
        with patch.object(self.bnp._vo, "voice_over_character_ids", return_value=set()):
            baseline = self.build(shots, ents, language="zh")
        for row in (current, baseline):
            row.pop("generated_at", None)
        self.assertEqual(json.dumps(current, sort_keys=True), json.dumps(baseline, sort_keys=True))
        self.assertNotIn("voice_over_character_ids", current)

    def test_legacy_replay_keeps_native_generation(self):
        manifest = self.build([shot("E01-S01-01", 6.0, "The Ledger：Recorded.", speaker_id=LEDGER)],
                              entities(), env=LEGACY)
        spec = manifest["shots"][0]["prompt_spec"]
        self.assertEqual(spec["dialogue"], "The Ledger：Recorded.")
        self.assertNotIn("voice_over", spec)


class WindowRuleTests(EditorialBase):
    LINE = "The Ledger：Twelve anomalies. Eleven resolved. One unresolved."

    def test_window_runs_to_the_next_spoken_shot(self):
        # 6 words / 2.7 wps + 0.5 -> 3.0 s; + 0.3 lead-in = 3.3 s inside a 2 s shot + 3 s silent shot
        manifest = self.build([shot("E01-S01-01", 2.0, self.LINE, speaker_id=LEDGER),
                               shot("E01-S01-02", 3.0, cast=[ELIAS]),
                               shot("E01-S01-03", 3.0, "Elias：Wait.", cast=[ELIAS])], entities())
        self.assertEqual(len(manifest["shots"][0]["prompt_spec"]["voice_over"]), 1)

    def test_window_too_short_raises(self):
        with self.assertRaisesRegex(ValueError, r"^VOICE_OVER_WINDOW_TOO_SHORT:E01-S01-01:3\.30:2\.00$"):
            self.build([shot("E01-S01-01", 2.0, self.LINE, speaker_id=LEDGER),
                        shot("E01-S01-02", 3.0, "Elias：Wait.", cast=[ELIAS])], entities())

    def test_english_estimate_counts_words_and_zh_is_unchanged(self):
        npr = load("npr_voice_over", NALU_TOOLS / "nalu_prompt_rules.py")
        self.assertEqual(npr.min_dialogue_seconds("Twelve anomalies. Eleven resolved. One unresolved.", None, "en"), 3.0)
        self.assertEqual(npr.min_dialogue_seconds("陆哥我回来了", None), 2.0)
        self.assertEqual(npr.min_dialogue_seconds("陆哥我回来了", 5.0), npr.min_dialogue_seconds("陆哥我回来了", 5.0, "zh"))


class H3NoSpeechUnitTests(EditorialBase):
    def test_voice_over_only_unit_passes_crossmodal_gate_with_zero_speakers(self):
        manifest = self.build([shot("E01-S01-01", 4.0, "The Ledger：Subject: the Arbiter.", speaker_id=LEDGER)],
                              entities())
        unit = {"unit_id": "E01-VU-001", "model": "MiniMax-H3",
                "ordered_prompt_specs": [manifest["shots"][0]["prompt_spec"]],
                "speaker_voice_contract": {"bindings": []}, "provider_entity_token_map": {}}
        report = h3_gate.evaluate(unit)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["dialogue_speakers"], [])
        # the pre-change unit (V.O. line still in the video dialogue) is exactly the reported failure
        unit["ordered_prompt_specs"] = [{"dialogue": "The Ledger：Subject: the Arbiter."}]
        self.assertTrue(any(code.startswith("H3_SPEAKER_VOICE_CONTRACT_BINDING_MISSING")
                            or code.startswith("H3_CROSSMODAL_SPEAKER_COVERAGE_MISMATCH")
                            for code in h3_gate.evaluate(unit)["failures"]))

    def test_renderer_emits_the_no_speech_vocal_rule(self):
        try:  # reuse the renderer's own synthetic fixture builder
            from tools.tests.test_h3_shot_scope_v1 import A, build
        except ImportError as exc:  # not shipped in every portable bundle
            self.skipTest(f"H3 fixture builder unavailable: {exc}")
        from tools.h3_provider_prompt_renderer import render_h3_prompt
        unit, plan = build([{"cast": [A]}, {"cast": [A]}])   # V.O. removed -> no beat has dialogue
        unit["provider_scope_projection"]["visible_living_entity_instance_total"] = 1
        text, _ = render_h3_prompt(unit, plan)
        vocal = next(line for line in text.splitlines() if line.startswith("vocal_rule:"))
        self.assertIn("mouth closed", vocal)
        self.assertIn("No dialogue voice reference is required", text)

    def test_identity_plates_never_requested_for_the_narrator(self):
        editorial = {"voice_over_character_ids": [LEDGER], "shots": [{
            "shot_id": "S1", "prompt_spec": {"dialogue": "", "cast": [
                {"character": "Elias", "character_id": ELIAS},
                {"character": "The Ledger", "character_id": LEDGER}]}}]}
        anchor = {"units": [{"unit_id": "U1", "reference_image_paths": []}]}
        plan = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]}]}
        with patch.object(self.bnp, "_locked_identity_plate", return_value=None):
            missing = self.bnp.append_h3_identity_plates(anchor, plan, editorial, episode="E01")
        self.assertEqual(missing, [ELIAS])


class S1GateTests(unittest.TestCase):
    def contract(self):
        return {"episode": "E60", "character_entities": entities(), "shots": [{
            "shot_id": "S1", "target_seconds": 2.0,
            "prompt_spec": {"dialogue": "The Ledger：Twelve anomalies. Eleven resolved.", "cast": [
                {"character": "Elias", "character_id": ELIAS}],
                "action": {"primary_action": "Elias walks", "subject_id": ELIAS},
                "role_semantic_disambiguation": {
                    "primary_actor": "Elias", "primary_actor_id": ELIAS,
                    "dialogue_speaker": "The Ledger", "dialogue_speaker_id": LEDGER, "lip_owner_id": ""}}}]}

    def test_narrator_is_judged_as_an_offscreen_voice(self):
        with patch.dict(os.environ, CURRENT, clear=False):
            report = validate_character_entity_contract(self.contract())
        self.assertFalse([f for f in report["failures"] if "DIALOGUE_SPEAKER_NOT_IN_VISIBLE_CAST" in f], report)
        with patch.dict(os.environ, LEGACY, clear=False):
            legacy = validate_character_entity_contract(self.contract())
        self.assertIn(f"S1_DIALOGUE_SPEAKER_NOT_IN_VISIBLE_CAST:{LEDGER}", legacy["failures"])

    def test_static_design_r8_ignores_narration(self):
        gate = load("static_design_gate_vo", NALU_TOOLS / "static_design_gate.py")
        with patch.dict(os.environ, CURRENT, clear=False):
            report = gate.evaluate(self.contract(), gate.POLICY)
        flags = [flag for row in report["rows"] for flag in row["flags"]]
        self.assertFalse([f for f in flags if f.startswith("R8_")], flags)
        with patch.dict(os.environ, LEGACY, clear=False):
            legacy = gate.evaluate(self.contract(), gate.POLICY)
        self.assertTrue([f for row in legacy["rows"] for f in row["flags"] if f.startswith("R8_")])

    def test_writer_selfcheck_sees_only_in_video_dialogue(self):
        selfcheck = load("selfcheck_vo", NALU_TOOLS / "nalu_writer_selfcheck_seq29.py")
        contract = self.contract()
        contract["shots"][0]["target_seconds"] = 7.0
        with patch.dict(os.environ, CURRENT, clear=False):
            view = selfcheck.in_video_contract(contract)
        self.assertEqual(view["shots"][0]["prompt_spec"]["dialogue"], "")
        self.assertEqual(view["shots"][0]["_voice_over_lines"], 1)
        with patch.dict(os.environ, LEGACY, clear=False):
            self.assertIs(selfcheck.in_video_contract(contract), contract)


class PlacementTests(unittest.TestCase):
    LINES = [
        {"shot_id": "S1", "line_index": 0, "text": "a", "duration_seconds": 1.5},
        {"shot_id": "S1", "line_index": 1, "text": "b", "duration_seconds": 1.0},
        {"shot_id": "S2", "line_index": 0, "text": "c", "duration_seconds": 1.0},
    ]

    def test_lead_in_gap_and_separation(self):
        rows, failures = vo.place(self.LINES, {"S1": 10.0, "S2": 12.0}, [], picture_end=30.0)
        self.assertEqual(failures, [])
        self.assertEqual([(r["start"], r["end"]) for r in rows], [(10.3, 11.8), (12.05, 13.05), (13.25, 14.25)])

    def test_overlap_with_in_video_speech_blocks(self):
        _, failures = vo.place(self.LINES, {"S1": 10.0, "S2": 20.0}, [(12.5, 13.0)], picture_end=30.0)
        self.assertEqual(failures, ["VOICE_OVER_OVERLAPS_DIALOGUE:S1:1"])

    def test_past_picture_end_blocks(self):
        _, failures = vo.place(self.LINES[:1], {"S1": 10.0}, [], picture_end=11.0)
        self.assertEqual(failures, ["VOICE_OVER_RUNS_PAST_PICTURE_END:S1:0"])

    def test_duck_expression_is_unity_outside_windows(self):
        self.assertEqual(vo.duck_expression([]), "1")
        self.assertIn("0.3500", vo.duck_expression([(1.0, 2.0)]))


def write_binding_fixture(tmp: Path) -> tuple[Path, Path, Path]:
    wav = tmp / "S1_0.wav"
    wav.write_bytes(b"RIFF-fake-wav")
    manifest = tmp / "E01_voice_over_manifest.json"
    manifest.write_text(json.dumps({"schema": vo.MANIFEST_SCHEMA, "rows": [{
        "shot_id": "S1", "line_index": 0, "text": "Recorded.", "text_sha256": vo.text_sha256("Recorded."),
        "wav": str(wav), "wav_sha256": vo.file_sha256(wav), "duration_seconds": 1.0}]}))
    placement = tmp / "E01_voice_over_placement.json"
    placement.write_text(json.dumps({
        "schema": vo.PLACEMENT_SCHEMA, "voice_over_manifest": str(manifest),
        "voice_over_manifest_sha256": vo.file_sha256(manifest),
        "rows": [{"shot_id": "S1", "line_index": 0, "speaker": "The Ledger", "text": "Recorded.",
                  "start": 0.3, "end": 1.3, "wav": str(wav), "wav_sha256": vo.file_sha256(wav)}]}))
    return wav, manifest, placement


class BindingTests(unittest.TestCase):
    def test_bound_placement_is_admitted_and_tampering_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav, manifest, placement = write_binding_fixture(Path(tmp))
            self.assertEqual(vo.binding_failures(placement), [])
            self.assertEqual(leveller.voice_over_windows(placement), [(0.3, 1.3)])
            project = {"metadata": {"voice_over_narration": {
                "placement": str(placement), "placement_sha256": vo.file_sha256(placement)}},
                "timeline": {"audioTracks": [{"id": "Audio.VO", "clips": [
                    {"id": "vo1", "source": str(wav), "metadata": {"audio_origin": "VOICE_OVER_NARRATION"}}]}]}}
            failures, shas = apc.voice_over_binding_failures(project)
            self.assertEqual((failures, shas), ([], {vo.file_sha256(wav)}))
            profile = {"source_audio_policy": "PRESERVE_NATIVE_MULTIMODAL_AUDIO"}
            project["metadata"]["source_audio_policy"] = "PRESERVE_NATIVE_MULTIMODAL_AUDIO"
            self.assertEqual(apc._native_dialogue_binding_failures(project, profile), [])
            wav.write_bytes(b"swapped")  # the mixed audio is no longer the S4 wav
            self.assertIn("VOICE_OVER_WAV_SHA_MISMATCH:S1:0", vo.binding_failures(placement))
            with self.assertRaisesRegex(RuntimeError, "VOICE_OVER_PLACEMENT_UNBOUND"):
                leveller.voice_over_windows(placement)
            self.assertTrue(any(code.startswith("VOICE_OVER_AUDIO_NOT_BOUND")
                                for code in apc._native_dialogue_binding_failures(project, profile)))

    def test_undeclared_narration_clip_still_fails(self):
        project = {"metadata": {"source_audio_policy": "PRESERVE_NATIVE_MULTIMODAL_AUDIO"},
                   "timeline": {"audioTracks": [{"id": "A1", "clips": [
                       {"id": "vo1", "source": "/nope.wav", "metadata": {"audio_origin": "VOICE_OVER_NARRATION"}}]}]}}
        failures = apc._native_dialogue_binding_failures(
            project, {"source_audio_policy": "PRESERVE_NATIVE_MULTIMODAL_AUDIO"})
        self.assertEqual(failures, ["VOICE_OVER_AUDIO_NOT_BOUND:vo1"])


CONTRACT_S7 = {
    "episode": "E01", "character_entities": entities(),
    "shots": [{"shot_id": "S1", "scene_id": "SC1", "target_seconds": 2.0},
              {"shot_id": "S2", "scene_id": "SC1", "target_seconds": 3.0},
              {"shot_id": "S3", "scene_id": "SC1", "target_seconds": 3.0}],
    "audio_contract": {"dialogue_units": [
        {"shot_id": "S1", "speaker_id": LEDGER, "text": "Recorded.", "emotion": "calm"},
        {"shot_id": "S3", "speaker_id": ELIAS, "text": "Wait.", "emotion": "fear"}]},
}
GROUPING = {"units": [{"unit_id": "E01-VU-001", "editorial_shot_ids": ["S1", "S2"]},
                      {"unit_id": "E01-VU-002", "editorial_shot_ids": ["S3"]}]}


class SpeakerMapAndCaptionTests(unittest.TestCase):
    PLACEMENT = {"rows": [{"shot_id": "S1", "line_index": 0, "text": "Recorded.", "start": 0.3, "end": 1.2}]}

    def test_speaker_map_uses_placement_and_never_attributes_asr_to_the_narrator(self):
        smap = load("speaker_map_vo", NALU_TOOLS / "build_final_cut_speaker_map.py")
        timeline = {"segments": [{"unit_id": "E01-VU-001", "output_start": 0.0},
                                 {"unit_id": "E01-VU-002", "output_start": 5.0}]}
        result = smap.build_map(CONTRACT_S7, GROUPING, timeline, voice_over_placement=self.PLACEMENT)
        ledger = result["lines"][0]
        self.assertEqual((ledger["time"], ledger["end"], ledger["presence"]), (0.3, 1.2, "VOICE_OVER"))
        aligned = smap.align_with_unit_asr(result, {"E01-VU-001": [{"start": 2.5, "end": 3.0, "text": "hm"}],
                                                    "E01-VU-002": [{"start": 0.2, "end": 0.8, "text": "Wait."}]},
                                           CONTRACT_S7, GROUPING, timeline)
        self.assertEqual(aligned["lines"][0]["time"], 0.3)
        self.assertEqual([w.get("speaker") for w in aligned["asr_windows"]], [LEDGER, None, ELIAS])
        self.assertEqual(aligned["asr_windows"][0]["presence"], "VOICE_OVER")
        # without a placement the map is the old one
        plain = smap.build_map(CONTRACT_S7, GROUPING, timeline)
        self.assertNotIn("presence", plain["lines"][0])
        self.assertEqual(plain["lines"][0]["time"], 1.0)
        self.assertEqual(smap.shot_start_times(CONTRACT_S7, GROUPING, {"E01-VU-001": 0.0, "E01-VU-002": 5.0})[0],
                         {"S1": 0.0, "S2": 2.0, "S3": 5.0})

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_burnin_captions_take_voice_over_timing_from_the_placement(self):
        burnin = load("burnin_vo", NALU_TOOLS / "build_burnin_subtitles.py")
        self.assertEqual(burnin.voice_over_captions(CONTRACT_S7, None), {})
        self.assertEqual(burnin.voice_over_captions(CONTRACT_S7, self.PLACEMENT), {0: self.PLACEMENT["rows"][0]})
        project = {"timeline": {"videoTracks": [{"clips": [
            {"start": 0.0, "duration": 5.0, "in": 0.0, "metadata": {"source_id": "E01-VU-001"}},
            {"start": 5.0, "duration": 3.0, "in": 0.0, "metadata": {"source_id": "E01-VU-002"}}]}]}}
        asr = {"E01-VU-001": [], "E01-VU-002": [{"start": 0.2, "end": 0.8, "text": "Wait."}]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            paths = {}
            for name, payload in (("project", project), ("asr", asr), ("contract", CONTRACT_S7),
                                  ("grouping", GROUPING), ("placement", self.PLACEMENT)):
                paths[name] = tmp / f"{name}.json"
                paths[name].write_text(json.dumps(payload))
            argv = ["build", "--episode", "E01", "--project", str(paths["project"]), "--asr", str(paths["asr"]),
                    "--contract", str(paths["contract"]), "--grouping", str(paths["grouping"]),
                    "--source", str(tmp / "in.mp4"), "--out-ass", str(tmp / "s.ass"),
                    "--out-video", str(tmp / "out.mp4"), "--out-report", str(tmp / "r.json"),
                    "--language", "en", "--voice-over-placement", str(paths["placement"])]
            from PIL import ImageFont
            default_font = ImageFont.load_default()
            fake_run = SimpleNamespace(returncode=0, stderr="", stdout="")
            with patch.object(sys, "argv", argv), \
                    patch.object(burnin._media, "resolve_latin_font", return_value=("Fake.ttf", "TEST")), \
                    patch.object(burnin._media, "require_ffmpeg", return_value="ffmpeg"), \
                    patch.object(ImageFont, "truetype", return_value=default_font), \
                    patch.object(burnin.subprocess, "run", return_value=fake_run):
                self.assertEqual(burnin.main(), 0)
            rows = json.loads((tmp / "r.json").read_text())["rows"]
        self.assertEqual([(r["text"], r["start"], r["timing_basis"]) for r in rows],
                         [("Recorded.", 0.3, "VOICE_OVER_PLACEMENT"), ("Wait.", 5.12, "ASR_SEGMENT_MATCH")])
        self.assertEqual(rows[0]["end"], 1.28)


class SelectiveBgmDuckingTests(unittest.TestCase):
    def test_plan_ducks_music_under_voice_over(self):
        bgm = load("selective_bgm_vo", NALU_TOOLS / "nalu_selective_bgm.py")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            assembly = tmp / "assembly"
            assembly.mkdir()
            (tmp / "contract.json").write_text(json.dumps(CONTRACT_S7))
            (tmp / "grouping.json").write_text(json.dumps(GROUPING))
            (assembly / "E01_release_timeline.json").write_text(json.dumps({
                "content_runtime_seconds": 60.0, "segments": [
                    {"unit_id": "E01-VU-001", "output_start": 0.0, "output_end": 5.0},
                    {"unit_id": "E01-VU-002", "output_start": 5.0, "output_end": 8.0}]}))
            (assembly / "E01_unit_asr.json").write_text(json.dumps({}))
            (assembly / "E01_voice_over_placement.json").write_text(json.dumps(
                {"rows": [{"shot_id": "S1", "line_index": 0, "start": 0.3, "end": 1.2}]}))
            source_plan = {"cues": [{"cue_id": "C1", "narrative_function": "open", "shots": ["S1", "S2"],
                                     "source_key": "K1", "dialogue_duck_db": -12, "volume": 0.5}],
                           "generations": [{"source_key": "K1"}], "planned_credits": 0,
                           "planned_credits_basis": "test"}
            args = SimpleNamespace(episode="E01", contract=tmp / "contract.json", assembly=assembly,
                                   grouping=tmp / "grouping.json", project=None, work=tmp / "work",
                                   bgm_transactions_dir=None)
            with patch.object(bgm, "_load_current_source_plan", return_value=source_plan), \
                    patch.object(bgm, "sha256_file", return_value="0" * 64):
                bgm.cmd_plan(args)
            plan = json.loads((assembly / "E01_BGM_PLAN.json").read_text())
        windows = plan["cues"][0]["dialogue_windows"]
        self.assertEqual([(w["start"], w["end"], w.get("source")) for w in windows], [(0.3, 1.2, "VOICE_OVER")])
        self.assertTrue(plan["cues"][0]["dialogue_present"])


class ContractDetectionTests(unittest.TestCase):
    """contract_has_voice_over drives the S2 fingerprint (one re-run for in-flight episodes)."""

    def contract(self, dialogue: str, ents: list[dict]) -> dict:
        return {"dialogue_language": "en", "character_entities": ents,
                "shots": [shot("E01-S01-01", 6.0, dialogue)]}

    def test_detects_a_narrated_contract_only_under_current_portable(self):
        narrated = self.contract("The Ledger：It was recorded.", entities())
        with patch.dict(os.environ, CURRENT, clear=False):
            self.assertTrue(vo.contract_has_voice_over(narrated))
            self.assertFalse(vo.contract_has_voice_over(self.contract("Elias：Who is there?", entities())))
            self.assertFalse(vo.contract_has_voice_over(self.contract("Elias：Who is there?",
                                                                      entities(with_ledger=False))))
        with patch.dict(os.environ, LEGACY, clear=False):
            self.assertFalse(vo.contract_has_voice_over(narrated))


class S4SynthesisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load("nalu_pipeline_vo", NALU_TOOLS / "nalu_pipeline.py")

    def ctx(self, tmp: Path, calls: list):
        editorial = {"shots": [{"shot_id": "E01-S01-01", "prompt_spec": {"dialogue": "", "voice_over": [
            {"line_index": 0, "speaker": "The Ledger", "character_id": LEDGER, "text": "Recorded."}]}}]}
        (tmp / "editorial.json").write_text(json.dumps(editorial))
        (tmp / "contract.json").write_text(json.dumps(CONTRACT_S7 | {"audio_contract": {"dialogue_units": [
            {"shot_id": "E01-S01-01", "speaker_id": LEDGER, "text": "Recorded.", "emotion": "calm"}]}}))
        (tmp / "registry.json").write_text(json.dumps({"major_roles": [
            {"entity_id": "ledger", "character_id": LEDGER, "voice_id": "voice-ledger-1",
             "status": "LOCKED_PRODUCTION_READY"}]}))
        (tmp / "payloads.json").write_text(json.dumps({"tasks": [
            {"entity_id": "ledger", "character_id": LEDGER, "request": {"emotion": "neutral", "speed": 0.9}}]}))
        p = SimpleNamespace(editorial=tmp / "editorial.json", contract=tmp / "contract.json",
                            voice=tmp / "voice", speech_payloads=tmp / "payloads.json",
                            scope={"voice_registry": tmp / "registry.json", "scope_id": "TWELVE-GAZES"})

        def paid_step(argv, **kwargs):
            calls.append([str(x) for x in argv])
            out_dir = Path(argv[argv.index("--output-dir") + 1])
            (out_dir / str(argv[argv.index("--file-name") + 1])).write_bytes(b"mp3")
            return self.pipeline.PASS, {"name": kwargs["name"], "exit_code": 0}

        def run(argv, **kwargs):
            Path(argv[-1]).write_bytes(b"RIFF-wav")
            return {"name": kwargs["name"], "exit_code": 0}

        return SimpleNamespace(p=p, episode="E01", language="en", paid_step=paid_step, run=run,
                               planned_commands=[], say=lambda *_: None)

    def test_synthesizes_once_and_is_idempotent(self):
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ctx = self.ctx(tmp, calls)
            with patch.object(self.pipeline, "voice_over_asr", return_value={"recall": 1.0, "transcript": "Recorded."}), \
                    patch.object(self.pipeline, "media_seconds", return_value=1.1), \
                    patch.object(self.pipeline._media, "require_ffmpeg", return_value="ffmpeg"):
                res = self.pipeline.StageResult(self.pipeline.PASS)
                self.pipeline.s4_voice_over(ctx, res)
                self.assertEqual((res.status, res.blockers), (self.pipeline.PASS, []))
                manifest = json.loads(self.pipeline.voice_over_manifest_path(ctx).read_text())
                row = manifest["rows"][0]
                self.assertTrue(manifest["complete"])
                self.assertEqual((row["shot_id"], row["line_index"], row["text_sha256"], row["duration_seconds"]),
                                 ("E01-S01-01", 0, vo.text_sha256("Recorded."), 1.1))
                self.assertTrue(row["transaction"].endswith(
                    f"/TWELVE-GAZES/E01/voice_over/E01-S01-01_0_{vo.text_sha256('Recorded.')[:12]}.json"))
                argv = calls[0]
                self.assertEqual(argv[argv.index("speech-generate") + 1], "Recorded.")
                self.assertEqual([argv[argv.index(f) + 1] for f in ("--voice-id", "--emotion", "--speed")],
                                 ["voice-ledger-1", "calm", "0.9"])
                self.assertIn("--paid", argv)
                res2 = self.pipeline.StageResult(self.pipeline.PASS)
                self.pipeline.s4_voice_over(ctx, res2)
                self.assertEqual((len(calls), res2.status), (1, self.pipeline.PASS))

    def test_edited_line_gets_a_new_transaction(self):
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ctx = self.ctx(tmp, calls)
            with patch.object(self.pipeline, "voice_over_asr", return_value={"recall": 1.0, "transcript": "x"}), \
                    patch.object(self.pipeline, "media_seconds", return_value=1.1), \
                    patch.object(self.pipeline._media, "require_ffmpeg", return_value="ffmpeg"):
                self.pipeline.s4_voice_over(ctx, self.pipeline.StageResult(self.pipeline.PASS))
                editorial = json.loads((tmp / "editorial.json").read_text())
                editorial["shots"][0]["prompt_spec"]["voice_over"][0]["text"] = "Recorded twice."
                (tmp / "editorial.json").write_text(json.dumps(editorial))
                res = self.pipeline.StageResult(self.pipeline.PASS)
                self.pipeline.s4_voice_over(ctx, res)
        transactions = [argv[argv.index("--transaction") + 1] for argv in calls]
        self.assertEqual((res.status, len(transactions), len(set(transactions))), (self.pipeline.PASS, 2, 2))

    def test_s4_fingerprint_follows_the_narration_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ctx = self.ctx(tmp, [])
            first = self.pipeline.fp_s4(ctx)
            self.assertIsNotNone(first)
            editorial = json.loads((tmp / "editorial.json").read_text())
            editorial["shots"][0]["prompt_spec"]["voice_over"][0]["text"] = "Recorded twice."
            (tmp / "editorial.json").write_text(json.dumps(editorial))
            self.assertNotEqual(self.pipeline.fp_s4(ctx), first)
            editorial["shots"][0]["prompt_spec"].pop("voice_over")
            (tmp / "editorial.json").write_text(json.dumps(editorial))
            self.assertIsNone(self.pipeline.fp_s4(ctx))  # no narration: S4 skip behaviour unchanged

    def test_asr_mismatch_blocks_without_retry(self):
        calls: list = []
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.ctx(Path(tmp), calls)
            with patch.object(self.pipeline, "voice_over_asr", return_value={"recall": 0.2, "transcript": "x"}), \
                    patch.object(self.pipeline, "media_seconds", return_value=1.1), \
                    patch.object(self.pipeline._media, "require_ffmpeg", return_value="ffmpeg"):
                res = self.pipeline.StageResult(self.pipeline.PASS)
                self.pipeline.s4_voice_over(ctx, res)
        self.assertEqual(res.status, self.pipeline.BLOCKED)
        self.assertEqual(res.blockers, ["VOICE_OVER_ASR_MISMATCH:E01-S01-01:0"])
        self.assertEqual(len(calls), 1)

    def test_narrator_without_locked_voice_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = self.ctx(Path(tmp), [])
            Path(ctx.p.scope["voice_registry"]).write_text(json.dumps({"major_roles": []}))
            res = self.pipeline.StageResult(self.pipeline.PASS)
            self.pipeline.s4_voice_over(ctx, res)
        self.assertEqual(res.blockers, [f"VOICE_OVER_VOICE_NOT_LOCKED:{LEDGER}"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class S7MixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load("nalu_pipeline_vo_mix", NALU_TOOLS / "nalu_pipeline.py")

    def test_real_mix_keeps_video_bit_exact_and_writes_a_bound_placement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            picture, wav = tmp / "picture.mp4", tmp / "line.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x112:d=8:r=24",
                            "-f", "lavfi", "-i", "sine=frequency=220:duration=8", "-shortest",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-ar", "48000",
                            str(picture)], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
                            "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True)
            editorial = {"shots": [{"shot_id": "S1", "prompt_spec": {"voice_over": [
                {"line_index": 0, "speaker": "The Ledger", "character_id": LEDGER, "text": "Recorded."}]}}]}
            (tmp / "editorial.json").write_text(json.dumps(editorial))
            (tmp / "contract.json").write_text(json.dumps(CONTRACT_S7))
            (tmp / "grouping.json").write_text(json.dumps(GROUPING))
            project = {"timeline": {"videoTracks": [{"clips": [
                {"start": 0.0, "duration": 5.0, "in": 0.0, "metadata": {"source_id": "E01-VU-001"}},
                {"start": 5.0, "duration": 3.0, "in": 0.0, "metadata": {"source_id": "E01-VU-002"}}]}]}}
            (tmp / "project.json").write_text(json.dumps(project))
            p = SimpleNamespace(editorial=tmp / "editorial.json", contract=tmp / "contract.json",
                                grouping_plan=tmp / "grouping.json", agentcut_project=tmp / "project.json",
                                assembly=tmp, voice=tmp / "voice")
            ctx = SimpleNamespace(p=p, episode="E01")
            manifest = self.pipeline.voice_over_manifest_path(ctx)
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"schema": vo.MANIFEST_SCHEMA, "rows": [{
                "shot_id": "S1", "line_index": 0, "speaker": "The Ledger", "character_id": LEDGER,
                "text": "Recorded.", "text_sha256": vo.text_sha256("Recorded."), "wav": str(wav),
                "wav_sha256": vo.file_sha256(wav), "duration_seconds": 1.0}]}))
            res = self.pipeline.StageResult(self.pipeline.BLOCKED)
            # in-video speech of unit 2 starts at 5.2 s: the V.O. (0.3-1.3 s) is clear of it
            asr = {"E01-VU-002": [{"start": 0.2, "end": 1.0, "text": "Wait."}]}
            mixed, blockers = self.pipeline.s7_voice_over(ctx, res, picture, asr)
            self.assertEqual(blockers, [])
            self.assertEqual(mixed.name, "E01_picture_native_vo.mp4")
            self.assertEqual(self.pipeline._video_stream_hash(picture), self.pipeline._video_stream_hash(mixed))
            placement = self.pipeline.voice_over_placement_path(ctx)
            rows = json.loads(placement.read_text())["rows"]
            self.assertEqual((rows[0]["start"], rows[0]["end"]), (0.3, 1.3))
            self.assertEqual(vo.binding_failures(placement), [])
            declared = json.loads((tmp / "project.json").read_text())["metadata"]["voice_over_narration"]
            self.assertEqual(apc.voice_over_binding_failures({"metadata": {"voice_over_narration": declared}})[0], [])
            # the 880 Hz narration is audible inside its window; outside it the native bed is untouched
            def mean_db(path: Path, start: float, seconds: float, band: str) -> float:
                out = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(seconds), "-i", str(path),
                                      "-af", f"{band},volumedetect", "-f", "null", "-"],
                                     capture_output=True, text=True).stderr
                return float(out.split("mean_volume:")[1].split("dB")[0])
            high = ",".join(["highpass=f=600"] * 4)
            self.assertGreater(mean_db(mixed, 0.5, 0.6, high), mean_db(picture, 0.5, 0.6, high) + 15)
            low = ",".join(["lowpass=f=400"] * 4)
            self.assertLess(mean_db(mixed, 0.5, 0.6, low), mean_db(picture, 0.5, 0.6, low) - 6)   # ducked to 0.35
            self.assertAlmostEqual(mean_db(mixed, 3.0, 1.0, low), mean_db(picture, 3.0, 1.0, low), delta=1.0)
            # a transcript segment in a unit with no in-video dialogue is the S6-cleared ambience
            # hallucination, not speech: it does not block
            hallucination = {"E01-VU-001": [{"start": 0.5, "end": 1.0, "text": "Hello."}]}
            self.assertEqual(self.pipeline.s7_voice_over(ctx, res, picture, hallucination)[1], [])
            # once the unit carries in-video dialogue, the same overlap blocks
            editorial["shots"].append({"shot_id": "S2", "prompt_spec": {"dialogue": "Elias：Hello."}})
            (tmp / "editorial.json").write_text(json.dumps(editorial))
            _, blocked = self.pipeline.s7_voice_over(ctx, res, picture, hallucination)
            self.assertEqual(blocked, ["VOICE_OVER_OVERLAPS_DIALOGUE:S1:0"])


if __name__ == "__main__":
    unittest.main()


class PromptBatchAndTimingTests(unittest.TestCase):
    """Twelve Gazes E01 S5: prompt batch QA still expected narration verbatim in the H3 prompt."""

    def contract(self) -> dict:
        return {"character_entities": entities(), "shots": [
                    {"shot_id": "E01-S01-01", "scene_id": "S1", "target_seconds": 6.0},
                    {"shot_id": "E01-S01-02", "scene_id": "S1", "target_seconds": 6.0}],
                "scene_states": [{"scene_id": "S1", "source_events": ["EV-1"]}],
                "audio_contract": {"dialogue_units": [
                    {"shot_id": "E01-S01-01", "speaker_id": LEDGER, "text": "It was recorded."},
                    {"shot_id": "E01-S01-02", "speaker_id": LEDGER, "text": "It was recorded."},
                    {"shot_id": "E01-S01-02", "speaker_id": ELIAS, "text": "Not yet."}]}}

    def test_narration_is_not_expected_in_the_video_prompt(self):
        pbq = load("prompt_batch_qa_vo", NALU_TOOLS / "prompt_batch_qa.py")
        id2name = {LEDGER: "The Ledger", ELIAS: "Elias"}
        with patch.dict(os.environ, CURRENT, clear=False):
            dialogue, narration = pbq.dialogue_expectations(self.contract(), id2name)
        self.assertEqual(dialogue, {"E01-S01-02": ["Elias：Not yet."]})
        self.assertEqual(narration, {"E01-S01-01": ["It was recorded."], "E01-S01-02": ["It was recorded."]})
        with patch.dict(os.environ, LEGACY, clear=False):
            dialogue, narration = pbq.dialogue_expectations(self.contract(), id2name)
        self.assertEqual((len(dialogue["E01-S01-01"]), narration), (1, {}))

    def test_timing_map_never_assigns_narration_to_a_video_unit(self):
        from tools.unit_timing_map import build_timing_map
        grouping = {"units": [{"unit_id": "E01-VU-001", "editorial_shot_ids": ["E01-S01-01"], "duration_seconds": 6},
                              {"unit_id": "E01-VU-002", "editorial_shot_ids": ["E01-S01-02"], "duration_seconds": 6}]}
        with patch.dict(os.environ, CURRENT, clear=False):
            report = build_timing_map(self.contract(), grouping)
        self.assertNotIn("DIALOGUE_GENERATED_BY_TWO_UNITS", [f["code"] for f in report["failures"]])
        rows = [line for unit in report["units"] for shot in unit["shots"] for line in shot["dialogue"]]
        self.assertEqual(sorted(str(r.get("sound_source") or r["sound_source_unit_id"]) for r in rows),
                         ["E01-VU-002", "VOICE_OVER_S4", "VOICE_OVER_S4"])

