"""WP5 music (Bilibili benchmark 2026-11-23, ``~/nalu_lab/bili_work/CHANGE_SPEC.md``).

B (BILI_V1): the bed plays at 0.24 instead of 0.14 with the same -10 dB duck (pauses +4.7 dB), full level only 0.4 s
away from a line; the final-cut pad follows.  C (``bgm_mood_cues``): 2-3 mood cues from a series palette, one cue per
run of same-mood scenes, at most 3, a hard stop on a marked beat, each mood paid once per series (series cache).
LEGACY series are unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _p in (str(NALU_TOOLS), str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bgm_cue_shaping as sh  # noqa: E402
import nalu_bgm_default as bgm_default  # noqa: E402

sbgm = importlib.import_module("nalu_selective_bgm")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(moods, *, seconds=4.0, shots_per_scene=4, profile="BILI_V1", mood_switch=True, extra_cards=None,
             roles=None):
    """Scenes S01..Sn with ``shots_per_scene`` shots of ``seconds``; ``moods`` = one mood (or None) per scene."""
    shots, plan = [], []
    for n, mood in enumerate(moods, 1):
        sid = f"E05-S{n:02d}"
        for i in range(1, shots_per_scene + 1):
            shot = {"shot_id": f"{sid}-{i:02d}", "scene_id": sid, "target_seconds": seconds}
            role = (roles or {}).get(shot["shot_id"])
            if role:
                shot["prompt_spec"] = {"beat_role": role}
            shots.append(shot)
        card = {"scene_id": sid, **({"mood": mood} if mood else {}), **((extra_cards or {}).get(sid) or {})}
        plan.append(card)
    payload = {"episode": "E05", "shots": shots, "audio_contract": {"bgm": "NO_BGM"}, "pacing": {"scene_plan": plan}}
    if profile:
        payload["craft_profile"] = profile
    if mood_switch:
        payload["bgm_mood_cues"] = True
    return payload


class PaletteTests(unittest.TestCase):
    def test_six_moods_with_distinct_instrumental_briefs(self) -> None:
        palette = bgm_default.load_palette()
        self.assertEqual(set(palette["moods"]),
                         {"tender", "comic_bounce", "heartbreak", "tension", "triumph", "mystery"})
        briefs = [row["brief"] for row in palette["moods"].values()]
        self.assertEqual(len(set(briefs)), 6)
        for brief in briefs:
            self.assertIn("no vocals", brief)
        self.assertEqual(palette["max_cues_per_episode"], 3)

    def test_aliases_resolve(self) -> None:
        palette = bgm_default.load_palette()
        for value, key in (("TENDER", "tender"), ("comic-bounce", "comic_bounce"), ("悬疑", "mystery"),
                           ("爽", "triumph"), ("紧张", "tension"), ("心碎", "heartbreak"), ("nonsense", None)):
            self.assertEqual(bgm_default._mood_key(value, palette), key, value)


class MoodGroupingTests(unittest.TestCase):
    def test_consecutive_same_mood_scenes_are_one_cue_and_moods_are_inherited(self) -> None:
        c = contract(["tension", None, "tension", "tender", "tender"])
        decision = bgm_default.resolve(c)
        self.assertEqual(decision["source"], "LINE_DEFAULT")
        bgm = decision["declaration"]
        self.assertTrue(bgm["mood_cues"] and bgm["series_cache"])
        self.assertEqual([cue["mood"] for cue in bgm["cues"]], ["tension", "tender"])
        # 80 s total, coverage limit 64 s: the opening shots of the first cue are trimmed (the hook stays dry)
        covered = sum(4.0 for cue in bgm["cues"] for _ in cue["shots"])
        self.assertLessEqual(covered, 80 * bgm_default.MAX_DEFAULT_COVERAGE_RATIO)
        self.assertEqual(bgm["cues"][1]["shots"][0], "E05-S04-01")       # the mood change sits on a scene cut
        self.assertEqual(bgm["cues"][1]["shots"][-1], "E05-S05-04")      # runs to the end
        self.assertEqual(bgm["cues"][0]["narrative_function"], "MOOD_TENSION")

    def test_cap_three_cues_and_three_sources(self) -> None:
        c = contract(["tension", "tender", "mystery", "triumph", "heartbreak", "tender"], shots_per_scene=4)
        cues = bgm_default.resolve(c)["declaration"]["cues"]
        self.assertLessEqual(len(cues), 3)
        self.assertLessEqual(len({cue["brief"] for cue in cues}), 3)
        for cue in cues:
            self.assertGreaterEqual(len(cue["shots"]) * 4.0, bgm_default.MIN_MOOD_CUE_SECONDS)

    def test_short_mood_run_joins_its_longer_neighbour(self) -> None:
        c = contract(["tension", "tension", "comic_bounce", "tender", "tender"], shots_per_scene=3, seconds=4.0)
        # comic_bounce is a single 12 s scene: long enough to stand; a 2-shot (8 s) run is not
        c["shots"] = [s for s in c["shots"] if s["shot_id"] != "E05-S03-03"]
        moods = [cue["mood"] for cue in bgm_default.resolve(c)["declaration"]["cues"]]
        self.assertNotIn("comic_bounce", moods)
        self.assertLessEqual(len(moods), 3)

    def test_no_marked_mood_keeps_the_line_default(self) -> None:
        c = contract([None, None, None])
        self.assertEqual(bgm_default.resolve(c)["policy"], bgm_default.DEFAULT_POLICY_ID)

    def test_legacy_and_switch_off_are_byte_identical_to_before(self) -> None:
        base = contract(["tension", "tender", "tender"], profile=None, mood_switch=False)
        reference = bgm_default.resolve(copy.deepcopy(base))
        for variant in (contract(["tension", "tender", "tender"], profile=None, mood_switch=True),   # LEGACY + flag
                        contract(["tension", "tender", "tender"], profile="BILI_V1", mood_switch=False),
                        contract(["tension", "tender", "tender"], profile="LEGACY", mood_switch=True)):
            got = bgm_default.resolve(variant)
            self.assertEqual(json.dumps(got, sort_keys=True), json.dumps(reference, sort_keys=True))
        self.assertEqual(reference["policy"], bgm_default.DEFAULT_POLICY_ID)

    def test_authored_selective_cues_win_over_moods(self) -> None:
        c = contract(["tension", "tender"])
        c["audio_contract"]["bgm"] = {"mode": "SELECTIVE", "cues": [
            {"cue_id": "X", "shots": ["E05-S01-01"], "narrative_function": "DREAD", "brief": "strings"}]}
        self.assertEqual(bgm_default.resolve(c)["source"], "AUTHORED")

    def test_music_passage_is_never_trimmed(self) -> None:
        roles = {"E05-S01-01": "MUSIC_PASSAGE"}
        c = contract(["tender", "tender", "tension"], roles=roles)
        first = bgm_default.resolve(c)["declaration"]["cues"][0]
        self.assertEqual(first["shots"][0], "E05-S01-01")


class HardStopTests(unittest.TestCase):
    def test_scene_card_music_stop_splits_on_the_punchline(self) -> None:
        roles = {"E05-S02-03": "PUNCHLINE"}
        c = contract(["comic_bounce", "comic_bounce", "comic_bounce", "tender"],
                     extra_cards={"E05-S02": {"music_stop": True}}, roles=roles)
        bgm = bgm_default.resolve(c)["declaration"]
        self.assertEqual(bgm["hard_stop_shots"], ["E05-S02-03"])
        all_shots = [s for cue in bgm["cues"] for s in cue["shots"]]
        self.assertNotIn("E05-S02-03", all_shots)      # the punchline and the rest of its scene stay dry
        self.assertNotIn("E05-S02-04", all_shots)
        self.assertLessEqual(len(bgm["cues"]), 3)

    def test_shaper_ends_on_the_stop_with_a_short_fade_and_never_merges_across(self) -> None:
        tl = [{"shot_id": f"S{i}", "t0": 4.0 * i, "t1": 4.0 * (i + 1), "scene_id": f"SC{i // 4}",
               "shot": {"shot_id": f"S{i}", "scene_id": f"SC{i // 4}"}} for i in range(12)]
        cues = [{"cue_id": "A", "source_key": "K", "t0": 0.0, "t1": 22.0},
                {"cue_id": "B", "source_key": "K", "t0": 32.0, "t1": 48.0}]
        out = sh.shape(cues, tl, 48.0, {"K": 120.0}, stops=[22.0])
        a = next(c for c in out["cues"] if c["cue_id"] == "A")
        self.assertEqual((a["t1"], a["end_type"], a["fade_out_s"]), (22.0, "HIT_STOP", sh.HARD_STOP_FADE_SECONDS))
        self.assertTrue(a["hard_stop"])
        self.assertEqual(out["merged"], [])
        # without the stop the same source closer than the flicker gap merges (unchanged LEGACY behaviour)
        legacy = sh.shape([dict(c, t0=c["t0"], t1=c["t1"]) for c in
                           ({"cue_id": "A", "source_key": "K", "t0": 0.0, "t1": 22.0},
                            {"cue_id": "B", "source_key": "K", "t0": 26.0, "t1": 48.0})], tl, 48.0, {"K": 120.0})
        self.assertEqual(legacy["merged"], [["A", "B"]])
        self.assertNotIn("stops", legacy["boundaries"])

    def test_no_stops_is_identical_to_before(self) -> None:
        tl = [{"shot_id": f"S{i}", "t0": 4.0 * i, "t1": 4.0 * (i + 1), "scene_id": f"SC{i // 3}",
               "shot": {"shot_id": f"S{i}", "scene_id": f"SC{i // 3}"}} for i in range(9)]
        cues = [{"cue_id": "A", "source_key": "K", "t0": 4.0, "t1": 23.0}]
        self.assertEqual(sh.shape(cues, tl, 36.0, {"K": 60.0}), sh.shape(cues, tl, 36.0, {"K": 60.0}, stops=[]))


class BedLevelTests(unittest.TestCase):
    def test_bed_volume(self) -> None:
        self.assertEqual(sh.bed_volume(None, bili_v1=False), 0.14)
        self.assertEqual(sh.bed_volume(None, bili_v1=True), 0.24)
        self.assertEqual(sh.bed_volume(0.14, bili_v1=True), 0.24)     # the documented boilerplate value
        self.assertEqual(sh.bed_volume(0.10, bili_v1=True), 0.10)     # a deliberate authored level stays
        self.assertEqual(sh.bed_volume(0.20, bili_v1=False), 0.20)
        self.assertAlmostEqual(20 * __import__("math").log10(0.24 / 0.14), 4.68, places=2)

    def test_duck_guard_widens_the_full_duck(self) -> None:
        cue = {"timeline_start": 0.0, "dialogue_duck_db": sh.DUCK_DB, "dialogue_windows": [{"start": 4.0, "end": 6.0}]}
        plain, guarded = sbgm.duck_expr(cue), sbgm.duck_expr({**cue, "duck_guard_s": sh.BILI_V1_DUCK_GUARD_S})
        self.assertIn("(t-(3.750))", plain)
        self.assertIn("(t-(3.600))", guarded)     # full level only 0.4 s before the line
        self.assertIn("((6.400)-t)", guarded)


class SourcePlanAndCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tx_base = self.root / "tasks" / "giggle_bgm_transactions" / "SERIES-A"
        self.cache = self.root / "runtime" / "sources" / "SERIES-A" / "bgm"
        self.env = mock.patch.dict(os.environ, {sbgm.SERIES_CACHE_ENV: str(self.cache)})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def derived(self, episode: str, payload: dict) -> Path:
        sealed = self.root / episode / f"{episode}_GENERATION_CONTRACT_v1.json"
        sealed.parent.mkdir(parents=True, exist_ok=True)
        sealed.write_text(json.dumps({**payload, "episode": episode}, ensure_ascii=False), encoding="utf-8")
        return Path(bgm_default.write_effective_contract(sealed, self.root / episode / "bgm/DEFAULT.json")["contract"])

    def paths(self, episode: str, contract_path: Path):
        return sbgm.Paths(episode, contract=contract_path, work=self.root / episode / "work",
                          transactions=(self.tx_base / episode).resolve())

    def complete(self, p, generation: dict, task: str) -> Path:
        candidate = p.work / generation["source_key"] / "bgm_candidate_1.mp3"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_bytes(f"audio-{generation['source_key']}".encode())
        tx_path = p.tx / f"{generation['source_key']}.json"
        tx_path.parent.mkdir(parents=True, exist_ok=True)
        tx_path.write_text(json.dumps({
            "schema": "qingshan.storyclaw_audio_transaction.v1", "state": "TERMINAL_COMPLETED", "task_id": task,
            "request": {"prompt_sha256": generation["prompt_sha256"], "instrumental": True},
            "paid_authority": {"config_lock": "1", "authorization_ref": "order-9", "order_seq": "9",
                               "orders_sha256": "b" * 64},
            "result": {"status": "completed", "files": [{"path": str(candidate), "sha256": sha(candidate)}]}}),
            encoding="utf-8")
        return tx_path

    def plan(self, p, episode: str) -> dict:
        plan = sbgm._source_plan_payload(p, episode)
        sbgm.write_json(p.source_plan, plan)
        return plan

    def test_first_episode_pays_per_mood_second_episode_reuses_the_cache(self) -> None:
        moods = ["tension", "tension", "tender", "tender", "mystery", "mystery"]
        p1 = self.paths("E05", self.derived("E05", contract(moods)))
        plan1 = self.plan(p1, "E05")
        self.assertEqual(plan1["craft_profile"], "BILI_V1")
        self.assertTrue(plan1["series_cache"] and plan1["mood_cues"])
        self.assertEqual(len(plan1["generations"]), 3)
        self.assertEqual(plan1["planned_credits"], 24)                 # +24 on first use (3 moods x 8)
        self.assertEqual({c["volume"] for c in plan1["cues"]}, {0.24})
        pending, completed, blocked = sbgm._pending_generations(p1, plan1)
        self.assertEqual((len(pending), completed, blocked), (3, [], []))
        for i, gen in enumerate(plan1["generations"]):
            tx = self.complete(p1, gen, f"task-{i}")
            self.assertTrue(sbgm._completed_transaction(tx, gen)[0])
            sbgm.store_in_series_cache(p1, gen, tx)
        # second episode, same three moods, different scenes: zero new paid sources, nothing in its ledger store
        p2 = self.paths("E06", self.derived("E06", contract(["mystery", "mystery", "tender", "tender", "tension", "tension"])))
        plan2 = self.plan(p2, "E06")
        pending, completed, blocked = sbgm._pending_generations(p2, plan2)
        self.assertEqual((pending, blocked), ([], []))
        self.assertEqual(len(completed), 3)
        self.assertFalse(p2.tx.exists() and any(p2.tx.glob("*.json")))
        self.assertTrue(sbgm._series_cache_only(p2))
        for gen in plan2["generations"]:
            record = sbgm.transaction_path(p2, gen, plan2)
            self.assertTrue(str(record).startswith(str(self.cache)))
        # a cached file that no longer matches its sha is not reused (a fresh, paid source instead)
        gen = plan2["generations"][0]
        record = sbgm.transaction_path(p2, gen, plan2)
        cached_file = Path(json.loads(record.read_text())["result"]["files"][0]["path"])
        cached_file.write_bytes(b"tampered")
        pending, _, _ = sbgm._pending_generations(p2, plan2)
        self.assertEqual([g["source_key"] for g in pending], [gen["source_key"]])

    def test_s7_plan_carries_the_profile_the_guard_and_the_hard_stop(self) -> None:
        roles = {"E05-S03-03": "PUNCHLINE"}
        payload = contract(["comic_bounce"] * 3 + ["tender"] * 3, roles=roles,
                           extra_cards={"E05-S03": {"music_stop": True}})
        derived = self.derived("E05", payload)
        p = self.paths("E05", derived)
        plan = self.plan(p, "E05")
        self.assertEqual(plan["hard_stop_shots"], ["E05-S03-03"])
        shots = [s["shot_id"] for s in payload["shots"]]
        p.grouping.parent.mkdir(parents=True, exist_ok=True)
        p.grouping.write_text(json.dumps({"units": [{"unit_id": f"U{i}", "editorial_shot_ids": [sid]}
                                                    for i, sid in enumerate(shots)]}), encoding="utf-8")
        p.assembly.mkdir(parents=True, exist_ok=True)
        p.release_timeline.write_text(json.dumps({"content_runtime_seconds": 96.0, "segments": [
            {"unit_id": f"U{i}", "output_start": 4.0 * i, "output_end": 4.0 * (i + 1)} for i in range(len(shots))]}),
            encoding="utf-8")
        p.unit_asr.write_text(json.dumps({"U20": [{"start": 1.0, "end": 2.5}]}), encoding="utf-8")
        with mock.patch.object(sbgm, "longest_source_seconds", return_value=120.0):
            code = sbgm.cmd_plan(__import__("argparse").Namespace(
                episode="E05", contract=derived, assembly=p.assembly, grouping=p.grouping, project=None,
                work=p.work, bgm_transactions_dir=p.tx))
        out = json.loads(p.plan.read_text(encoding="utf-8"))
        self.assertEqual(code, 0, out.get("failures"))
        self.assertEqual(out["craft_profile"], "BILI_V1")
        stop_t = 4.0 * shots.index("E05-S03-03")
        stopped = [c for c in out["cues"] if c.get("hard_stop")]
        self.assertEqual(len(stopped), 1)
        self.assertAlmostEqual(stopped[0]["timeline_start"] + stopped[0]["duration"], stop_t, places=3)
        self.assertEqual(stopped[0]["fade_out_s"], sh.HARD_STOP_FADE_SECONDS)
        for cue in out["cues"]:
            self.assertEqual(cue["volume"], 0.24)
            self.assertEqual(cue["dialogue_duck_db"], -10.0)
            self.assertEqual(cue["duck_guard_s"], sh.BILI_V1_DUCK_GUARD_S)
            self.assertFalse(cue["timeline_start"] < stop_t < cue["timeline_start"] + cue["duration"] - 1e-6)

    def test_legacy_source_plan_has_no_new_keys_and_keeps_volume(self) -> None:
        payload = contract(["tension", "tender"], profile=None, mood_switch=False)
        p = self.paths("E07", self.derived("E07", payload))
        plan = self.plan(p, "E07")
        for key in ("craft_profile", "mood_cues", "series_cache", "hard_stop_shots"):
            self.assertNotIn(key, plan)
        self.assertEqual(plan["cues"][0]["volume"], 0.14)
        # no series cache without the opt-in, even when a cache record would exist
        gen = plan["generations"][0]
        self.assertEqual(sbgm.transaction_path(p, gen, plan), p.tx / f"{gen['source_key']}.json")

    def test_bili_v1_without_mood_cues_raises_only_the_bed(self) -> None:
        payload = contract(["tension", "tender"], profile="BILI_V1", mood_switch=False)
        p = self.paths("E08", self.derived("E08", payload))
        plan = self.plan(p, "E08")
        self.assertEqual(plan["craft_profile"], "BILI_V1")
        self.assertNotIn("series_cache", plan)
        self.assertEqual(plan["cues"][0]["volume"], 0.24)
        self.assertEqual(plan["cues"][0]["cue_id"], bgm_default.DEFAULT_CUE_ID)

    def test_pipeline_credit_reconciliation_accepts_an_all_cached_episode(self) -> None:
        pipeline = importlib.import_module("nalu_pipeline")
        moods = ["tension", "tension", "tender", "tender"]
        p1 = self.paths("E05", self.derived("E05", contract(moods)))
        plan1 = self.plan(p1, "E05")
        for i, gen in enumerate(plan1["generations"]):
            sbgm.store_in_series_cache(p1, gen, self.complete(p1, gen, f"task-{i}"))
        p2 = self.paths("E06", self.derived("E06", contract(moods)))
        self.plan(p2, "E06")
        with mock.patch.object(pipeline, "selective_bgm_transaction_dir", return_value=p2.tx), \
                mock.patch.object(pipeline, "bgm_work_dir", return_value=p2.work):
            self.assertTrue(pipeline.bgm_credit_reconciled(mock.Mock(episode="E06")))
            (p2.work / "E06_BGM_SOURCE_PLAN.json").unlink()
            self.assertFalse(pipeline.bgm_credit_reconciled(mock.Mock(episode="E06")))


if __name__ == "__main__":
    unittest.main()
