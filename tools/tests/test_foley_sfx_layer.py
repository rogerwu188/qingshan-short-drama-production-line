"""lines/nalu/runtime/tools/foley_sfx_layer.py — free CC0 foley bus keyed to the generation contract
(line owner 2026-11-23).  Offline: synthetic WAV library, injected fetcher, no ffmpeg, no network."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import os
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"


def _load(name: str):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fx = _load("foley_sfx_layer")
SR = fx.SR


def noise_burst(seconds: float, level_dbfs: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(seconds * SR)).astype(np.float32)
    x *= fx.db_to_lin(level_dbfs) / (np.sqrt(np.mean(x ** 2)) + 1e-12)
    return np.stack([x, x], axis=1)


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def synthetic_library(root: Path, events: dict[str, int], *, bed_seconds: float = 6.0) -> dict:
    """events: {event: clip count}; writes WAVs + a manifest with real sha256 pins."""
    clips = []
    for e_index, (event, count) in enumerate(sorted(events.items())):
        for i in range(count):
            secs = bed_seconds if event.startswith("amb_") else 0.4
            rel = f"{'beds' if event.startswith('amb_') else 'spots'}/{event}_{i}.wav"
            write_wav(root / rel, noise_burst(secs, -12.0 - i, seed=100 * e_index + i))
            clips.append({"clip_id": f"{event}_{i}", "event": event, "kind": "bed" if event.startswith("amb_") else "spot",
                          "file": rel, "sha256": hashlib.sha256((root / rel).read_bytes()).hexdigest()})
    manifest = {"schema": "nalu.foley_library.v1", "pack_id": "test-pack", "clips": clips}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def shot(shot_id: str, scene: str, action: str, *, seconds: float = 2.0, emotion: str = "", sfx=None) -> dict:
    spec = {"action": {"primary_action": action, "performance": {"emotion": emotion}}}
    if sfx is not None:
        spec["sound"] = {"sfx": sfx}
    return {"shot_id": shot_id, "scene_id": scene, "target_seconds": seconds, "blocking": action, "prompt_spec": spec}


def contract(shots: list[dict], scenes: list[dict]) -> dict:
    return {"shots": shots, "scene_states": scenes, "audio_contract": {"dialogue_units": []}}


def segments_for(shots: list[dict]) -> list[dict]:
    rows, t = [], 0.0
    for i, s in enumerate(shots):
        rows.append({"unit_id": f"U{i + 1}", "output_start": t, "output_end": t + s["target_seconds"]})
        t += s["target_seconds"]
    return rows


class LexiconTests(unittest.TestCase):
    def events(self, text):
        return [h["event"] for h in fx.match_events(text)]

    def test_blade_draw_in_four_languages(self):
        for text, lang in (("He draws his sword.", "en"), ("她拔剑出鞘。", "zh"), ("刀を抜いた。", "ja"), ("칼을 뽑았다.", "ko")):
            hits = fx.match_events(text)
            self.assertIn("blade_draw", [h["event"] for h in hits], text)
            self.assertEqual(next(h for h in hits if h["event"] == "blade_draw")["lang"], lang)

    def test_common_actions_map_across_languages(self):
        self.assertIn("coins", self.events("掏出一袋银子放在桌上"))
        self.assertIn("coins", self.events("She pays two silver taels."))
        self.assertIn("footsteps", self.events("그는 천천히 걸어간다"))
        self.assertIn("door_open", self.events("ドアを開ける"))
        self.assertIn("door_close", self.events("He slams the door behind him."))
        self.assertIn("slap", self.events("她狠狠扇了他一个耳光"))
        self.assertIn("paper", self.events("She flips through the ledger pages."))
        self.assertIn("cup", self.events("店小二端上茶杯"))
        self.assertIn("body_fall", self.events("その男は倒れた"))
        self.assertIn("magic_whoosh", self.events("他运起灵力，剑气纵横"))
        self.assertIn("horse_gallop", self.events("一队人马策马而来"))
        self.assertIn("phone_notify", self.events("Her phone buzzes with a new message."))

    def test_negation_suppresses_the_event(self):
        self.assertNotIn("door_open", self.events("他没有推门"))
        self.assertNotIn("door_open", self.events("He does not open the door."))
        self.assertIn("door_open", self.events("He opens the door."))

    def test_no_false_hits_on_neutral_boilerplate(self):
        self.assertEqual(self.events("The declared subject is in the starting position with lips closed."), [])
        self.assertNotIn("whoosh", self.events("The shopkeeper flips through the pages."))
        self.assertNotIn("body_fall", self.events("Night falls over the town."))


class SceneProfileTests(unittest.TestCase):
    def test_teahouse_is_interior_with_indoor_crowd(self):
        prof = fx.scene_profile({"scene_id": "S1", "location_id": "LOC-ANCHENG-TEAHOUSE", "time_id": "白日"}, {}, [])
        self.assertTrue(prof["interior"])
        self.assertEqual([b["event"] for b in prof["beds"]], ["amb_crowd_indoor"])

    def test_forest_at_night_gets_insects_and_rain_layer(self):
        prof = fx.scene_profile({"scene_id": "S2", "location_id": "LOC-BAMBOO-FOREST", "time_id": "夜晚", "weather": "Light rain"}, {}, [])
        self.assertFalse(prof["interior"])
        self.assertEqual([b["event"] for b in prof["beds"]], ["amb_rain", "amb_insects"])

    def test_private_room_has_no_bed(self):
        prof = fx.scene_profile({"scene_id": "S3", "location_id": "LOC-INN-BEDROOM", "time_id": "夜"}, {}, [])
        self.assertTrue(prof["interior"])
        self.assertEqual(prof["beds"], [])

    def test_footsteps_resolve_by_surface(self):
        self.assertEqual(fx.resolve_footsteps("footsteps", {"interior": True}), "footsteps_indoor")
        self.assertEqual(fx.resolve_footsteps("footsteps", {"interior": False}), "footsteps_outdoor")
        self.assertEqual(fx.resolve_footsteps("footsteps", {"interior": False, "snow": True}), "footsteps_snow")


class PlacementTests(unittest.TestCase):
    AVAILABLE = set(fx.EVENT_RULES)

    def plan(self, shots, windows=(), scenes=None):
        c = contract(shots, scenes or [{"scene_id": "S1", "location_id": "LOC-TEAHOUSE"}])
        segs = segments_for(shots)
        spans = fx.shot_spans(segs, fx.unit_shot_map(segs, None, c), {s["shot_id"]: s for s in shots})
        profiles = {sc["scene_id"]: fx.scene_profile(sc, c, shots) for sc in c["scene_states"]}
        return fx.plan_events(c, spans, list(windows), profiles, self.AVAILABLE)

    def test_action_lands_after_the_shots_dialogue(self):
        events, _ = self.plan([shot("A", "S1", "She draws her sword.", seconds=4.0)], windows=[(0.2, 2.0)])
        self.assertEqual(events[0]["event"], "blade_draw")
        self.assertAlmostEqual(events[0]["t"], 2.12, places=2)
        self.assertEqual(events[0]["placement"], "AFTER_DIALOGUE")

    def test_without_dialogue_the_action_is_near_shot_onset(self):
        events, _ = self.plan([shot("A", "S1", "x", seconds=2.0), shot("B", "S1", "He slams the door.", seconds=2.0)])
        self.assertEqual([e["event"] for e in events], ["door_close"])
        self.assertAlmostEqual(events[0]["t"], 2.0 + 0.35, places=2)

    def test_authored_offset_wins(self):
        events, _ = self.plan([shot("A", "S1", "x", seconds=3.0, sfx=[{"event": "knock", "at_s": 1.25}])])
        self.assertEqual(events[0]["event"], "knock")
        self.assertAlmostEqual(events[0]["t"], 1.25, places=3)
        self.assertEqual(events[0]["trigger"]["field"], "sound.sfx")

    def test_multiple_events_stagger_and_cap(self):
        text = "He draws his sword, kicks the table, smashes the cup and slaps the guard; coins scatter."
        events, skipped = self.plan([shot("A", "S1", text, seconds=4.0)])
        self.assertEqual(len(events), fx.MAX_EVENTS_PER_SHOT)
        ts = [e["t"] for e in events]
        self.assertEqual(ts, sorted(ts))
        self.assertTrue(all(b - a >= fx.STAGGER_S - 1e-6 for a, b in zip(ts, ts[1:])))
        self.assertIn("SHOT_EVENT_CAP", {s["reason"] for s in skipped})

    def test_heartbeat_is_capped_per_episode(self):
        shots = [shot(f"S{i}", "S1", "x", emotion="恐惧") for i in range(5)]
        events, skipped = self.plan(shots)
        self.assertEqual(sum(e["event"] == "heartbeat" for e in events), fx.EPISODE_CAPS["heartbeat"])
        self.assertIn("EPISODE_CAP", {s["reason"] for s in skipped})

    def test_missing_event_in_library_is_skipped_not_fatal(self):
        c = contract([shot("A", "S1", "He draws his sword.")], [{"scene_id": "S1", "location_id": "LOC-TEAHOUSE"}])
        segs = segments_for(c["shots"])
        spans = fx.shot_spans(segs, fx.unit_shot_map(segs, None, c), {"A": c["shots"][0]})
        events, skipped = fx.plan_events(c, spans, [], {}, available={"coins"})
        self.assertEqual(events, [])
        self.assertEqual(skipped[0]["reason"], "NO_CLIP_IN_LIBRARY")

    def test_energy_windows_stand_in_for_missing_line_windows(self):
        native = np.zeros((SR * 4, 2), dtype=np.float32)
        native[SR:int(2.5 * SR)] = noise_burst(1.5, -20.0, seed=3)
        rows = fx.energy_speech_windows(native)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][0], 1.0, delta=0.06)
        self.assertAlmostEqual(rows[0][1], 2.5, delta=0.06)

    def test_grouping_plan_splits_unit_span_by_shot_seconds(self):
        shots = [shot("A", "S1", "x", seconds=1.0), shot("B", "S1", "y", seconds=3.0)]
        grouping = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["A", "B"]}]}
        segs = [{"unit_id": "U1", "output_start": 10.0, "output_end": 18.0}]
        spans = fx.shot_spans(segs, fx.unit_shot_map(segs, grouping, contract(shots, [])), {s["shot_id"]: s for s in shots})
        self.assertEqual([(r["shot_id"], r["start"], r["end"]) for r in spans], [("A", 10.0, 12.0), ("B", 12.0, 18.0)])


class VariationTests(unittest.TestCase):
    def test_never_same_clip_back_to_back(self):
        clips = [{"clip_id": f"c{i}", "event": "footsteps_indoor"} for i in range(3)]
        picker = fx.ClipPicker(clips, seed=3)
        picks = [picker.pick("footsteps_indoor")["clip_id"] for _ in range(60)]
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])))
        self.assertEqual(set(picks), {"c0", "c1", "c2"})

    def test_single_clip_event_still_plays(self):
        picker = fx.ClipPicker([{"clip_id": "only", "event": "knock"}], seed=1)
        self.assertEqual([picker.pick("knock")["clip_id"] for _ in range(3)], ["only"] * 3)
        self.assertIsNone(picker.pick("slap"))


class LevelAndDuckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = synthetic_library(self.root, {"slap": 2, "amb_crowd_indoor": 1})
        clips, _ = fx.verify_library(self.root, self.manifest)
        self.picker = fx.ClipPicker(clips, seed=5)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loudness_meter_matches_a_known_tone(self):
        t = np.arange(SR * 3) / SR
        tone = (np.sqrt(2) * fx.db_to_lin(-23.0) * np.sin(2 * math.pi * 1000 * t)).astype(np.float32)
        self.assertAlmostEqual(fx.loudness_lufs(np.stack([tone, tone], 1) / np.sqrt(2)), -23.0, delta=0.3)

    def test_spot_level_and_duck_under_speech(self):
        n = SR * 6
        native = np.zeros((n, 2), dtype=np.float32)
        native[int(3.0 * SR):int(5.0 * SR)] = noise_burst(2.0, -18.0, seed=9)  # "speech" 3–5 s
        events = [{"event": "slap", "t": 1.0}, {"event": "slap", "t": 3.6}]
        sfx, placed, _ = fx.render_layer(native, events, [], self.picker, [(3.0, 5.0)], seed=1)
        clear = fx.loudness_lufs(sfx[int(1.0 * SR):int(1.4 * SR)], block_s=0.1, gated=False)
        under = fx.loudness_lufs(sfx[int(3.6 * SR):int(4.0 * SR)], block_s=0.1, gated=False)
        self.assertAlmostEqual(clear, fx.EVENT_RULES["slap"]["lufs"], delta=1.0)
        self.assertLessEqual(under, clear - 9.0)            # ducked ≥ ~10 dB inside the line window
        self.assertNotEqual(placed[0]["hits"][0]["clip_id"], placed[1]["hits"][0]["clip_id"])

    def test_bed_level_in_band(self):
        n = SR * 8
        native = np.zeros((n, 2), dtype=np.float32)
        beds = [{"event": "amb_crowd_indoor", "scene_id": "S1", "start": 0.0, "end": 8.0, "trigger": {}}]
        sfx, _, placed_beds = fx.render_layer(native, [], beds, self.picker, [], seed=1)
        level = fx.loudness_lufs(sfx[int(2 * SR):int(6 * SR)])
        self.assertTrue(-32.0 <= level <= -28.0, level)
        self.assertEqual(placed_beds[0]["target_lufs"], fx.BED_TARGET_LUFS)
        self.assertLess(float(np.abs(sfx[:10]).max()), 1e-3)   # faded in

    def test_peak_ceiling_scales_a_spot_on_a_hot_programme(self):
        n = SR * 2
        native = noise_burst(2.0, -6.0, seed=4).astype(np.float32)
        native = np.clip(native, -0.7, 0.7)
        sfx, placed, _ = fx.render_layer(native, [{"event": "slap", "t": 0.5}], [], self.picker, [], seed=1)
        self.assertLessEqual(float(np.abs(native + sfx).max()), fx.db_to_lin(fx.PEAK_CEIL_DBFS) + 1e-4)
        self.assertTrue(placed)
        base = np.full((100, 2), 0.6, np.float32)
        scale = fx._fit_under_ceiling(base, np.full((100, 2), 0.5, np.float32), fx.db_to_lin(fx.PEAK_CEIL_DBFS))
        self.assertLess(scale, 1.0)
        self.assertLessEqual(0.6 + 0.5 * scale, fx.db_to_lin(fx.PEAK_CEIL_DBFS) + 1e-4)


class FailOpenTests(unittest.TestCase):
    def test_missing_library_is_silence_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"pack_id": "x", "clips": [{"clip_id": "a", "event": "slap", "file": "spots/a.wav", "sha256": "0" * 64}]}
            lib = fx.ensure_library(manifest, Path(tmp) / "lib", allow_fetch=False)
            self.assertEqual(lib["status"], "LIBRARY_MISSING")
            self.assertIn("FETCH_DISABLED", lib["problems"])
            native = np.zeros((SR, 2), dtype=np.float32)
            sfx, record = fx.build_sfx_layer(native, [], None, {}, [], library=lib, env={})
            self.assertEqual(record["status"], "LIBRARY_MISSING")
            self.assertFalse(np.any(sfx))

    def test_switch_off(self):
        sfx, record = fx.build_sfx_layer(np.zeros((100, 2), np.float32), [], None, {}, [], env={"NALU_SFX": "0"})
        self.assertEqual(record["status"], "DISABLED")
        self.assertFalse(np.any(sfx))
        self.assertTrue(fx.enabled({}))

    def test_sha_mismatch_clip_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = synthetic_library(root, {"slap": 2})
            (root / manifest["clips"][0]["file"]).write_bytes(b"tampered")
            clips, problems = fx.verify_library(root, manifest)
            self.assertEqual([c["clip_id"] for c in clips], ["slap_1"])
            self.assertTrue(problems[0].startswith("CLIP_SHA_MISMATCH"))

    def test_fetch_failure_and_bad_digest_are_fail_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = {"pack_id": "x", "pack": {"url": "https://github.com/o/r/releases/download/t/p.zip", "size_bytes": 3, "sha256": "f" * 64},
                        "clips": [{"clip_id": "a", "event": "slap", "file": "a.wav", "sha256": "0" * 64}]}

            def boom(url, size):
                raise OSError("offline")
            lib = fx.ensure_library(manifest, Path(tmp) / "lib", allow_fetch=True, fetcher=boom)
            self.assertEqual(lib["status"], "LIBRARY_MISSING")
            self.assertTrue(lib["problems"][0].startswith("FETCH_FAILED"))
            lib = fx.ensure_library(manifest, Path(tmp) / "lib", allow_fetch=True, fetcher=lambda u, s: b"abc")
            self.assertIn("PACK_SHA_MISMATCH", lib["problems"][0])

    def test_verified_pack_installs_only_pinned_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            manifest = synthetic_library(src, {"slap": 1, "coins": 1})
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for clip in manifest["clips"]:
                    zf.write(src / clip["file"], clip["file"])
                zf.writestr("../escape.txt", "nope")
                zf.writestr("unlisted.wav", "nope")
            body = buf.getvalue()
            manifest["pack"] = {"url": "https://github.com/o/r/releases/download/t/p.zip", "size_bytes": len(body),
                                "sha256": hashlib.sha256(body).hexdigest()}
            lib_dir = Path(tmp) / "cache" / "pack"
            lib = fx.ensure_library(manifest, lib_dir, allow_fetch=True, fetcher=lambda u, s: body)
            self.assertEqual(lib["status"], "READY_FETCHED")
            self.assertFalse((lib_dir / "unlisted.wav").exists())
            self.assertFalse((Path(tmp) / "cache" / "escape.txt").exists())
            again = fx.ensure_library(manifest, lib_dir, allow_fetch=False)
            self.assertEqual(again["status"], "READY")

    def test_download_refuses_non_github_hosts(self):
        with self.assertRaises(RuntimeError):
            fx._download("https://example.com/p.zip", 10)

    def test_render_error_is_fail_open(self):
        lib = {"status": "READY", "clips": [{"clip_id": "a", "event": "knock", "path": "/nonexistent.ogg"}]}
        c = contract([shot("A", "S1", "Someone knocks.")], [{"scene_id": "S1", "location_id": "LOC-INN-HALL"}])

        def bad_decoder(path):
            raise RuntimeError("decode failed")
        sfx, record = fx.build_sfx_layer(np.zeros((SR * 2, 2), np.float32), segments_for(c["shots"]), None, c, [],
                                         library=lib, env={}, decoder=bad_decoder)
        self.assertEqual(record["status"], "ERROR_FAIL_OPEN")
        self.assertFalse(np.any(sfx))


class MixIntegrationTests(unittest.TestCase):
    """final_cut_audio_bed.foley_bus: the S7 hook with a tiny synthetic library (env-selected manifest + dir)."""

    def test_hook_adds_events_and_writes_the_episode_record(self):
        bed = _load("final_cut_audio_bed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lib"
            synthetic_library(root, {"blade_draw": 2, "cloth": 2, "amb_crowd_indoor": 1})
            shots = [shot("A", "S1", "x", seconds=2.0), shot("B", "S1", "She draws her sword and turns.", seconds=3.0)]
            c = contract(shots, [{"scene_id": "S1", "location_id": "LOC-TEAHOUSE"}])
            segs = segments_for(shots)
            native = np.zeros((SR * 5, 2), dtype=np.float32)
            native[: SR] = noise_burst(1.0, -18.0, seed=2)
            report = Path(tmp) / "E99_AUDIO_BED.json"
            env = {"NALU_FOLEY_MANIFEST": str(root / "manifest.json"), "NALU_FOLEY_DIR": str(root), "NALU_SFX": "1"}
            with mock.patch.dict(os.environ, env):
                sfx, record = bed.foley_bus(native, segs, {}, c, [{"start": 0.0, "end": 1.0}], native, 12, report)
            self.assertEqual(record["status"], "APPLIED", record)
            self.assertEqual(sfx.shape, native.shape)
            self.assertEqual({e["event"] for e in record["events"]}, {"blade_draw", "cloth"})
            self.assertEqual([b["event"] for b in record["beds"]], ["amb_crowd_indoor"])
            draw = next(e for e in record["events"] if e["event"] == "blade_draw")
            self.assertAlmostEqual(draw["t"], 2.35, places=2)
            self.assertGreater(float(np.abs(sfx[int(2.35 * SR):int(2.6 * SR)]).max()), 0.01)
            saved = json.loads((Path(tmp) / "E99_SFX_LAYER.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["counts"]["events"], 2)
            self.assertEqual(record["record_path"], str(Path(tmp) / "E99_SFX_LAYER.json"))

    def test_hook_with_switch_off_returns_silence(self):
        bed = _load("final_cut_audio_bed")
        with mock.patch.dict(os.environ, {"NALU_SFX": "off"}):
            sfx, record = bed.foley_bus(np.ones((SR, 2), np.float32) * 0.1, [], {}, {}, [], np.zeros((SR, 2), np.float32), 1, None)
        self.assertEqual(record["status"], "DISABLED")
        self.assertFalse(np.any(sfx))


class RepositoryManifestTests(unittest.TestCase):
    def test_pinned_manifest_is_cc0_and_complete(self):
        manifest = fx.load_manifest(fx.CONFIG_PATH)
        pack = manifest["pack"]
        self.assertTrue(pack["url"].startswith("https://github.com/"))
        self.assertRegex(pack["sha256"], r"^[0-9a-f]{64}$")
        self.assertLessEqual(pack["size_bytes"], 30 * 1024 * 1024)
        clips = manifest["clips"]
        self.assertTrue(40 <= len(clips) <= 120, len(clips))
        events = {c["event"] for c in clips}
        for needed in ("footsteps_indoor", "footsteps_outdoor", "door_open", "door_close", "cloth", "blade_draw",
                       "blade_clash", "punch", "slap", "body_fall", "cup", "paper", "coins", "amb_crowd_indoor",
                       "amb_crowd_outdoor", "amb_wind", "amb_rain", "amb_fire", "amb_birds", "amb_insects",
                       "phone_notify", "car_pass", "horse_gallop", "magic_whoosh", "magic_impact", "heartbeat", "stinger"):
            self.assertIn(needed, events)
        for clip in clips:
            self.assertEqual(clip["source"]["license"], "CC0-1.0", clip["clip_id"])
            self.assertRegex(clip["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(clip["event"] in fx.EVENT_RULES or clip["event"] in fx.BED_EVENTS, clip["event"])


if __name__ == "__main__":
    unittest.main()
