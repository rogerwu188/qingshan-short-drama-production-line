"""PERFORMANCE_VARIETY_V1 + casting / speaker voice gender (line owner 2026-11-20, JA-01 anime E02).

Offline: no provider call, synthetic tones only.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
RT = ROOT / "lines/nalu/runtime/tools"
for p in (str(ROOT), str(RT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools import performance_variety as pv  # noqa: E402
from tools import voice_speaker_consistency as vsc  # noqa: E402
from tools.h3_provider_prompt_renderer import render_h3_prompt  # noqa: E402
from tools.tests import test_h3_director_prompt_v2 as T  # noqa: E402
from tools.tests.test_h3_shot_scope_v1 import A, B, build  # noqa: E402
import voice_gender as vg  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as grp  # noqa: E402
import nalu_knowledge_events as nke  # noqa: E402


def _shot(i: int, scene: str, speaker: str = "CHAR-A", cast=("CHAR-A", "CHAR-B"), *, emotion: str = "",
          scale: str = "MEDIUM", dialogue: str = "A：说吧。", business: str = "", body: str = "") -> dict:
    perf = {"emotion": emotion, **({"business_en": business} if business else {}), **({"body_action": body} if body else {})}
    return {"shot_id": f"S{i:02d}", "scene_id": scene, "shot_size": scale,
            "prompt_spec": {"dialogue": dialogue, "camera_plan": {"shot_scale": scale},
                            "cast": [{"character_id": c} for c in cast],
                            "role_semantic_disambiguation": {"dialogue_speaker_id": speaker},
                            "action": {"performance": perf}}}


class GestureTrackerTest(unittest.TestCase):
    def test_no_repeat_within_window_and_scene_cap(self):
        shots = [_shot(i, f"SC{i // 6}", emotion="冷") for i in range(18)]
        receipt = pv.assign_episode(shots)
        fams = [r["family"] for r in receipt["rows"]]
        self.assertEqual(len(fams), 18)
        for i in range(len(fams)):
            self.assertNotIn(fams[i], fams[max(0, i - pv.WINDOW + 1):i], (i, fams))
        self.assertEqual(receipt["violations"], [])
        for scene in {r["scene_id"] for r in receipt["rows"]}:
            counts = {}
            for r in receipt["rows"]:
                if r["scene_id"] == scene:
                    counts[r["family"]] = counts.get(r["family"], 0) + 1
            self.assertLessEqual(max(counts.values()), pv.SCENE_CAP)

    def test_stock_spread_avoided_unless_called(self):
        shots = [_shot(i, "SC1", emotion="求") for i in range(10)]
        rows = pv.assign_episode(shots)["rows"]
        self.assertNotIn(pv.STOCK_FAMILY, [r["family"] for r in rows])
        # an authored stock gesture without a motive is replaced; with a shrug beat it is kept
        authored = pv.assign_episode([_shot(1, "SC1", business="spreads both hands outward")])["rows"][0]
        self.assertEqual(authored["source"], "AUTHORED_STOCK_REPLACED")
        self.assertNotEqual(authored["family"], pv.STOCK_FAMILY)
        called = pv.assign_episode([_shot(1, "SC1", dialogue="A：我能怎么办？", body="无奈地摊手")])["rows"][0]
        self.assertEqual(called["family"], pv.STOCK_FAMILY)

    def test_close_up_gets_face_business_and_mannerism_first(self):
        rows = pv.assign_episode([_shot(i, "SC1", scale="CLOSE_UP") for i in range(6)])["rows"]
        self.assertTrue(all(pv.VOCAB[r["family"]][1] == pv.FACE for r in rows), rows)
        shot = _shot(1, "SC1")
        rows = pv.assign_episode([shot], {"CHAR-A": {"mannerisms": ["twists a silver ring"]}})["rows"]
        self.assertEqual(rows[0]["business_en"], "twists a silver ring")
        self.assertEqual(rows[0]["source"], "MANNERISM")
        action = shot["prompt_spec"]["action"]
        self.assertEqual(action["performance_business_en"], "twists a silver ring")
        self.assertIn("CHAR-B", action["listener_business_en"])            # the listener reacts
        self.assertNotIn("mouth", action["listener_business_en"]["CHAR-B"])

    def test_offscreen_speaker_gets_no_business_and_authored_wins(self):
        rows = pv.assign_episode([_shot(1, "SC1", speaker="CHAR-C", cast=("CHAR-B",))])["rows"]
        self.assertEqual(rows, [])
        rows = pv.assign_episode([_shot(1, "SC1", business="adjusts one cuff, eyes on him")])["rows"]
        self.assertEqual((rows[0]["source"], rows[0]["family"]), ("AUTHORED_BUSINESS_EN", "cuff"))


def _two_beat():
    unit, plan = T.fixture()
    u2, p2 = build([{"cast": [A, B], "speaker": A}, {"cast": [B], "speaker": A, "shot_id": "T-S02"}],
                   camera_plan=T.CAMERA)
    unit["ordered_prompt_specs"] = u2["ordered_prompt_specs"]
    for spec in unit["ordered_prompt_specs"]:
        spec["role_semantic_disambiguation"].update(primary_actor_id=A, dialogue_speaker_id=A, dialogue_listener_id=B)
    plan.update(beats=p2["beats"], role_bindings=p2["role_bindings"], duration_seconds=p2["duration_seconds"])
    english = unit["h3_provider_english_contract"]
    english["beats"] = [english["beats"][0], {"entry_state": "Beta stands right", "primary_action": "Beta listens",
                                              "exit_state": "Beta stands right"}]
    return unit, plan


class DirectorPromptTest(unittest.TestCase):
    def test_business_listener_and_never_line(self):
        unit, plan = T.fixture()
        unit["ordered_prompt_specs"][0]["action"] = {
            "performance_business_en": "adjusts one cuff with the other hand",
            "listener_business_en": {B: "nods once, slowly"}}
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("While speaking, Alpha adjusts one cuff with the other hand.", text)
        self.assertIn("Beta listens without speaking and nods once, slowly.", text)
        self.assertIn(pv.NEVER_STOCK, text.split("Never: ", 1)[1])
        plain, _ = render_h3_prompt(*T.fixture())
        self.assertNotIn("hand-spreading", plain)       # no business -> no new Never item (bytes unchanged)

    def test_voice_gender_named_on_the_audio_reference(self):
        unit, plan = T.fixture()
        unit["character_entities"][0]["appearance_ch1"] = "二十岁女性，短发。"
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("@Audio1 is Alpha's voice, a woman's voice.", text)

    def test_speaker_offscreen_in_one_beat_is_marked_there(self):
        unit, plan = _two_beat()
        unit["ordered_prompt_specs"][1]["action"] = {"performance_business_en": "folds the arms"}
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("Alpha speaks line 2 from offscreen. Beta only listens with lips closed", text)
        self.assertIn("2. Alpha (offscreen, not shown)", text)
        self.assertIn("during an offscreen line everyone on screen keeps the lips closed", text)
        self.assertNotIn("While speaking, Alpha folds the arms", text)      # no body business offscreen
        self.assertIn("1. Alpha, 0–3 s:", text)


class CastingGenderTest(unittest.TestCase):
    ENTITIES = [{"character_id": "CHAR-REI-TAYLOR", "appearance_ch1": "A young woman of twenty-two, black bob",
                 "apparent_age_range": "20-24"},
                {"character_id": "CHAR-CLAIRE", "appearance_ch1": "a girl of seventeen"},
                {"character_id": "CHAR-KEN", "gender": "male"}]

    def test_device_case_rei_recast_to_a_female_voice(self):
        catalog = {"rei_taylor": {"voice_id": "Japanese_OptimisticYouth"},
                   "claire": {"voice_id": "Japanese_DecisivePrincess"},
                   "ken": {"voice_id": "Japanese_DominantMan"}}
        plan = vg.plan_casting(self.ENTITIES, catalog, language="ja",
                               voice_cast={"characters": {"CHAR-REI-TAYLOR": {"reference_f0_hz": 198}}})
        self.assertEqual(plan["counts"]["MISMATCH"], 1)
        recast = plan["recasts"][0]
        self.assertEqual((recast["character_id"], recast["from_voice_id"]), ("CHAR-REI-TAYLOR", "Japanese_OptimisticYouth"))
        self.assertEqual(vg.SYSTEM_VOICE_GENDER[recast["to_voice_id"]], "female")
        self.assertNotEqual(recast["to_voice_id"], "Japanese_DecisivePrincess")  # Claire's voice stays hers

    def test_f0_is_secondary_and_ambiguous_band_is_review(self):
        self.assertEqual(vg.f0_gender(120), "male")
        self.assertEqual(vg.f0_gender(260), "female")
        self.assertIsNone(vg.f0_gender(198))
        ch = vg.character_gender({"gender": "female"})
        only_f0 = vg.casting_check(ch, vg.voice_gender("clone_x", f0=120))
        self.assertEqual(only_f0["status"], vg.REVIEW)              # never a recast on F0 alone
        ambiguous = vg.casting_check(ch, vg.voice_gender("clone_x", f0=190))
        self.assertEqual(ambiguous["status"], vg.REVIEW)
        catalog_row = vg.voice_gender("v9", catalog=[{"voice_id": "v9", "gender": "male"}])
        self.assertEqual((catalog_row["gender"], catalog_row["basis"]), ("male", "PROVIDER_CATALOG"))
        self.assertEqual(vg.character_gender({"appearance_ch1": "女扮男装的少女，身穿男装"})["gender"], "female")

    def test_s4_check_rewrites_catalog_and_supersedes_locked_row(self):
        import nalu_pipeline as P
        tmp = Path(tempfile.mkdtemp())
        try:
            runtime = tmp / "runtime"
            runtime.mkdir()
            (runtime / "voice_catalog.json").write_text(json.dumps({"voices": {
                "rei_taylor": {"voice_id": "Japanese_OptimisticYouth", "casting_rationale": "optimistic"}}}))
            (runtime / "voice_registry.json").write_text(json.dumps({"major_roles": [
                {"entity_id": "rei_taylor", "character_id": "rei_taylor", "voice_id": "Japanese_OptimisticYouth",
                 "status": "LOCKED_PRODUCTION_READY"}]}))
            (tmp / "contract.json").write_text(json.dumps({"character_entities": self.ENTITIES[:1]}))
            payloads = tmp / "payloads.json"
            payloads.write_text("{}")
            said = []
            ctx = SimpleNamespace(episode="E02", language="ja", say=said.append, p=SimpleNamespace(
                voice=tmp / "voice", contract=tmp / "contract.json", speech_payloads=payloads,
                scope={"voice_catalog": runtime / "voice_catalog.json", "voice_registry": runtime / "voice_registry.json",
                       "voice_cast": runtime / "voice_cast.json", "scope_id": "ja01"}))
            out = P.s4_casting_gender_check(ctx)
            self.assertEqual(out["status"], "RECAST", out)
            catalog = json.loads((runtime / "voice_catalog.json").read_text())["voices"]["rei_taylor"]
            self.assertEqual(vg.SYSTEM_VOICE_GENDER[catalog["voice_id"]], "female")
            registry = json.loads((runtime / "voice_registry.json").read_text())
            self.assertEqual(registry["major_roles"], [])
            self.assertEqual(registry["superseded_rows"][0]["voice_id"], "Japanese_OptimisticYouth")
            self.assertFalse(payloads.exists())                    # payloads rebuilt from the new voice (free)
            self.assertTrue((tmp / "voice" / "voice_gender_check.json").is_file())
            self.assertTrue(any("VOICE_GENDER_RECAST" in line for line in said))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class VoiceSpeakerConsistencyTest(unittest.TestCase):
    def _task(self, *, url2="https://x/b.wav", cast2=(B,)):
        return {"task_key": "T1", "model": "MiniMax-H3", "reference_audio_urls": ["https://x/a.wav", url2],
                "machine_contract": {
                    "speaker_voice_contract": {"bindings": [
                        {"speaker": "阿尔", "character_id": A, "audio_slot": "@音频1", "voice_reference_url": "https://x/a.wav"},
                        {"speaker": "贝塔", "character_id": B, "audio_slot": "@音频2", "voice_reference_url": "https://x/b.wav"}]},
                    "character_entities": [{"character_id": A, "gender": "male"}, {"character_id": B, "gender": "female"}],
                    "ordered_prompt_specs": [
                        {"shot_id": "S1", "dialogue": "阿尔：好", "cast": [{"character_id": A}],
                         "role_semantic_disambiguation": {"dialogue_speaker_id": A}},
                        {"shot_id": "S2", "dialogue": "贝塔：好", "cast": [{"character_id": c} for c in cast2],
                         "role_semantic_disambiguation": {"dialogue_speaker_id": B}}]}}

    REGISTRY = [{"remote_url": "https://x/a.wav", "character_id": A, "voice_id": "Japanese_DominantMan"},
                {"remote_url": "https://x/b.wav", "character_id": B, "voice_id": "Japanese_OptimisticYouth"}]

    def test_flags_gender_order_and_unmarked_offscreen(self):
        prompt = "@Audio1 is Alpha's voice. @Audio2 is Beta's voice."
        report = vsc.check_task(self._task(), prompt, registry_rows=self.REGISTRY)
        self.assertTrue(any(i.startswith("VOICE_GENDER_CONTRADICTS_SPEAKER:贝塔:female:male") for i in report["issues"]))
        swapped = vsc.check_task(self._task(url2="https://x/a.wav"), prompt, registry_rows=self.REGISTRY)
        self.assertIn("AUDIO_SLOT_ORDER_MISMATCH", swapped["issues"])
        off = vsc.check_task(self._task(cast2=(A,)), prompt, registry_rows=self.REGISTRY[:1])
        self.assertIn(f"OFFSCREEN_SPEAKER_NOT_MARKED:S2:{B}", off["issues"])
        marked = vsc.check_task(self._task(cast2=(A,)), prompt + " Beta speaks from offscreen.",
                                registry_rows=self.REGISTRY[:1])
        self.assertEqual(marked["status"], "PASS")


class ReviewRoutingTest(unittest.TestCase):
    def test_classes_present_routed_and_global(self):
        self.assertEqual(grp.CLASS_TEXT["CRAFT-ACTING-MONOTONY"][0], "D")
        self.assertEqual(grp.CLASS_TEXT["QA-VOICE-GENDER"][0], "C")
        self.assertNotIn("CRAFT-ACTING-MONOTONY", grp.LANGUAGE_CLASSES)
        self.assertEqual(ffr.classify("CRAFT-ACTING-MONOTONY", ""), "ACTING_MONOTONY")
        self.assertEqual(ffr.fix_class("ACTING_MONOTONY"), ffr.RECORD)          # record + KB, not a paid redo
        self.assertEqual(ffr.classify(None, "every speaker spreads both hands outward on each line"), "ACTING_MONOTONY")
        self.assertEqual(ffr.classify("QA-VOICE-GENDER", ""), "VOICE_GENDER_MISMATCH")
        self.assertEqual(ffr.fix_class("VOICE_GENDER_MISMATCH"), ffr.PAID)
        self.assertIn("woman", ffr.redo_sentence(["VOICE_GENDER_MISMATCH"]))
        self.assertEqual(nke.FINAL_REVIEW_ROUTES["ACTING_MONOTONY"], "DIRECTING_GUIDANCE")
        for kind in ("ACTING_MONOTONY", "VOICE_GENDER_MISMATCH"):
            self.assertEqual(nke.final_review_scope({"item": None, "text": "x"}, kind)["scope"], "global")
        prompt = (ROOT / "skills/nalu-claude-code/scripts/codex_production.py").read_text(encoding="utf-8")
        self.assertIn("CRAFT-ACTING-MONOTONY", prompt)
        self.assertIn("QA-VOICE-GENDER", prompt)

    def test_casting_bug_is_mapping_bug_not_a_redo(self):
        check = ffr.voice_assignment_check(
            [{"speaker": "Rei", "character_id": "CHAR-REI", "voice_entity_id": "rei"}],
            [{"entity_id": "rei", "character_id": "CHAR-REI", "voice_id": "Japanese_OptimisticYouth"}],
            [{"character_id": "CHAR-REI", "appearance_ch1": "a young woman"}])
        self.assertEqual(check["status"], "MAPPING_BUG")
        self.assertEqual(check["bugs"][0]["problem"], "VOICE_GENDER_MALE_FOR_FEMALE_SPEAKER")


class F0DetectorTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg needed")
    def test_synthetic_tones_flag_a_male_voice_on_a_woman(self):
        import numpy as np
        import wave
        import unit_voice_consistency as uvc
        tmp = Path(tempfile.mkdtemp())
        try:
            sr = 16000
            t = np.arange(int(1.6 * sr)) / sr
            for name, f0 in (("low.wav", 118.0), ("high.wav", 245.0)):
                y = 0.4 * (2 * ((t * f0) % 1.0) - 1.0)
                with wave.open(str(tmp / name), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
                    w.writeframes((y * 32767).astype("<i2").tobytes())
            cast = {"characters": {"CHAR-REI": {"f0_band_hz": [200, 280], "gender": "female"}}}
            expected = [{"spoken_text": "Rei：こんにちは", "shot_id": "S1"}]
            segs = [{"start": 0.0, "end": 1.5, "text": "こんにちは"}]
            policy = {"min_attribution_similarity": 0.5}
            low = uvc.check_unit("U1", tmp / "low.wav", segs, expected, cast, {"Rei": "CHAR-REI"}, policy, language="ja")
            self.assertTrue(any(f.startswith("VOICE_GENDER_MISMATCH:CHAR-REI:female:male") for f in low["gender_flags"]),
                            low)
            high = uvc.check_unit("U1", tmp / "high.wav", segs, expected, cast, {"Rei": "CHAR-REI"}, policy, language="ja")
            self.assertEqual(high["gender_flags"], [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
