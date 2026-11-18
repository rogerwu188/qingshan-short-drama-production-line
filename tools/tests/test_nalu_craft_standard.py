"""NALU_CRAFT_STANDARD_v1 in the engine (line owner 2026-11-17, option A: no added cost, shot count unchanged).

Covers: the standard ships with a machine-readable item list; Codex's start prompt carries it as its own capped
section beside (not inside) 「本集导演经验」; the writer guidance no longer asks for establishing wides or 12 s
same-setup monologues; S7 cuts silent units to their v1 length around the motion peak (never dialogue, never under
the runtime floor); the reviewer's optional craft_standard block is parsed leniently and never gates; local pacing
metrics; top gaps become privacy-scrubbed CRAFT_STD_GAP|<id> knowledge events the collector clusters."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "skills" / "nalu-claude-code" / "scripts",
           ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_craft_standard as craft  # noqa: E402
import performance_cut as pc  # noqa: E402

STANDARD = craft.load_items(ROOT)


class StandardFilesTest(unittest.TestCase):
    def test_item_list_is_complete_and_machine_readable(self) -> None:
        self.assertEqual(STANDARD["standard_version"], "NALU_CRAFT_STANDARD_v1")
        items = STANDARD["items"]
        self.assertEqual(len(items), 26)
        self.assertEqual(sum(1 for i in items if i["severity"] == "CORE"), 21)
        for item in items:
            for key in ("id", "layer", "severity", "principle_zh", "principle_en", "reviewer_check_zh", "title_en"):
                self.assertTrue(item.get(key), (item["id"], key))
            self.assertIn(item["layer"], ("PACING_STRUCTURE", "CLARITY_GRAMMAR"))
            self.assertIn(item["default_fix_owner"], craft.FIX_OWNERS)
        self.assertTrue((ROOT / craft.STANDARD_MD).is_file())
        self.assertLessEqual(len(STANDARD["codex_compressed_zh"]), 1500)

    def test_standard_is_not_on_a_bucket_upload_path(self) -> None:
        for rel in ("tools/collective_learning/s3_sync.py", "tools/collective_learning/sync_client.py",
                    "tools/collective_learning/bundles.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("lines/nalu/standards", text, rel)
            self.assertNotIn("NALU_CRAFT_STANDARD", text, rel)


# --------------------------------------------------------------------------- Codex start prompt
class CodexInjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = dict(os.environ)
        self.runtime = Path(tempfile.mkdtemp()) / "nalu_runtime"
        os.environ.update(NALU_ENGINE_ROOT=str(ROOT), NALU_RUNTIME_ROOT=str(self.runtime))
        os.environ.pop(craft.ENV_SWITCH, None)
        import codex_production as cp
        self.cp = cp

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)

    def test_section_is_capped_and_carries_the_whole_compressed_standard(self) -> None:
        section = self.cp.craft_standard_section()
        self.assertTrue(section.startswith(craft.SECTION_TITLE))
        self.assertLessEqual(len(section), craft.MAX_CODEX_SECTION_CHARS)
        self.assertIn(STANDARD["codex_compressed_zh"], section)          # not truncated
        self.assertIn("rg -n", section)                                  # look-up by grep, not a full read
        self.assertIn("beat_role", section)
        self.assertLessEqual(len(craft.codex_section(ROOT, limit=600)), 600)

    def test_separate_from_the_directing_guidance_section(self) -> None:
        guidance = "## 本集导演经验（集体知识库）\n" + "规则。" * 400          # its own 1500-char budget
        prompt = self.cp.build_prompt("E02", "派单附加说明", guidance)
        section = self.cp.craft_standard_section()
        self.assertEqual(prompt.count(craft.SECTION_TITLE), 1)
        self.assertTrue(prompt.endswith(guidance))                       # the KB section stays last, untouched
        self.assertLess(prompt.index(craft.SECTION_TITLE), prompt.index("## 本集导演经验"))
        self.assertNotIn(craft.SECTION_TITLE, guidance)
        self.assertIn(section + "\n\n" + guidance, prompt)
        # the receipt diff for the KB section excludes the craft section on both sides
        without = self.cp.build_prompt("E02", "派单附加说明", "", section)
        self.assertEqual(prompt, without + "\n\n" + guidance)

    def test_switch_off_and_missing_standard_leave_the_prompt_as_before(self) -> None:
        os.environ[craft.ENV_SWITCH] = "off"
        self.assertEqual(self.cp.craft_standard_section(), "")
        self.assertNotIn(craft.SECTION_TITLE, self.cp.build_prompt("E02", ""))
        os.environ.pop(craft.ENV_SWITCH)
        self.assertEqual(craft.codex_section(Path(tempfile.mkdtemp())), "")

    def test_production_contract_points_at_the_section(self) -> None:
        text = (ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").read_text(encoding="utf-8")
        self.assertIn("NALU 成片标准 v1", text)
        self.assertIn("rg -n -A8", text)


# --------------------------------------------------------------------------- writer guidance
class WriterGuidanceTest(unittest.TestCase):
    def test_old_wide_and_monologue_rules_are_gone(self) -> None:
        contract = (ROOT / "agent_factory/storyclaw_portable/WRITER_CONTRACT.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md").read_text(encoding="utf-8")
        self.assertNotIn("Open every new location with an establishing framing", contract)
        self.assertNotIn("open on a silent two-shot", contract)
        self.assertNotIn("write a silent 4 s cutaway", contract)
        self.assertNotIn("每场至少有远/中/近三种景别", guide)
        self.assertNotIn("开场一个交代空间和人物位置的远景或全景", guide)
        self.assertNotIn("要交代房间就写一个建立镜", guide)
        self.assertNotIn("组与组之间写一个 4 s 无台词的插入镜", guide)
        self.assertNotIn("每组 ≤12 s，组间一个 4 s 无台词插入镜", guide)
        self.assertNotIn("能写成 4 s 的动作就直接写 4 s", guide)
        self.assertIn("No establishing shots", contract)
        self.assertIn("prompt_spec.beat_role", contract)
        self.assertIn("不写建立镜", guide)
        self.assertIn("约 8 s", guide)
        # hard safety rules stay
        self.assertIn("## 1b. 内容安全", guide)
        self.assertIn("One H3 unit carries one speaker", contract)


# --------------------------------------------------------------------------- S7 peak-window trim
def shot(sid, target=None, role=None, bridge=None):
    spec: dict = {}
    if role:
        spec["beat_role"] = role
    if bridge:
        spec["transition"] = {"sound_bridge_from_previous_seconds": bridge}
    row = {"shot_id": sid, "prompt_spec": spec}
    if target is not None:
        row["target_seconds"] = target
    return row


def episode(units, *, lines=None, vo=None, shots=None, clip=4.458):
    """units: [(unit_id, [shot ids])]; lines: {shot_id: text}; returns (contract, grouping, plan report)."""
    lines = lines or {}
    contract = {"episode": "E03", "dialogue_language": "zh", "camera_grammar_policy": "CAMERA_GRAMMAR_V1",
                "shots": shots or [shot(s) for _, sids in units for s in sids],
                "audio_contract": {"dialogue_units": [{"shot_id": s, "speaker_id": "A", "text": t}
                                                      for s, t in lines.items()]}}
    grouping = {"units": [{"unit_id": u, "editorial_shot_ids": sids} for u, sids in units]}
    asr = {}
    for u, sids in units:
        text = "".join(lines.get(s, "") for s in sids)
        if text:
            asr[u] = [{"start": 0.5, "end": 0.5 + 0.2 * len(text), "text": text,
                       "words": [{"start": round(0.5 + 0.2 * i, 3), "end": round(0.7 + 0.2 * i, 3), "word": ch}
                                 for i, ch in enumerate(text)]}]
    report = pc.plan(contract, grouping, asr, {u: clip for u, _ in units}, vo_seconds=vo or {})
    return contract, grouping, report


def motion_peak_at(seconds, duration=4.458, fps=24, base=0.4, peak=6.0):
    n = int(duration * fps) - 1
    return [peak if abs((i + 1) / fps - seconds) <= 0.2 else base for i in range(n)]


def row(report, uid):
    return next(r for r in report["units"] if r["unit_id"] == uid)


class PeakWindowTest(unittest.TestCase):
    def test_peak_found_and_cut_just_after_it(self) -> None:
        win = pc.peak_window(motion_peak_at(3.2), 4.458, 2.5)
        self.assertEqual(win["signal"], "PEAK")
        self.assertAlmostEqual(win["end"] - win["start"], 2.5, places=3)
        self.assertLess(win["start"], 3.2)
        self.assertLess(3.2, win["end"])
        self.assertAlmostEqual((3.2 - win["start"]) / 2.5, pc.PEAK_POSITION, delta=0.08)

    def test_weak_signal_keeps_the_head(self) -> None:
        for motion in ([0.4] * 100, None, [0.4, 0.5], [1.0 + 0.3 * (i % 2) for i in range(100)]):
            win = pc.peak_window(motion, 4.458, 2.5)
            self.assertEqual((win["signal"], win["start"], win["end"]), ("WEAK", 0.0, 2.5), motion)

    def test_early_peak_clamps_to_the_head_and_late_peak_to_the_tail(self) -> None:
        self.assertEqual(pc.peak_window(motion_peak_at(0.6), 4.458, 2.5)["start"], 0.0)
        late = pc.peak_window(motion_peak_at(4.3), 4.458, 2.5)
        self.assertAlmostEqual(late["end"], 4.458, places=3)

    def test_lengths_follow_v1_reaction_and_silent_ranges(self) -> None:
        self.assertEqual(pc.target_length("REACTION", 4), 2.5)
        self.assertEqual(pc.target_length("REACTION", 1.0), 1.5)
        self.assertEqual(pc.target_length("REACTION", None), 2.0)
        self.assertEqual(pc.target_length("", 4), 3.0)
        self.assertEqual(pc.target_length("", 2.2), 2.2)
        self.assertEqual(pc.target_length("", None), 2.5)


class ApplyPeakWindowsTest(unittest.TestCase):
    UNITS = [("VU-001", ["S01"]), ("VU-002", ["S02"]), ("VU-003", ["S03"]), ("VU-004", ["S04"]),
             ("VU-005", ["S05"])]
    LINES = {"S01": "你敢动我试试", "S02": "董事长请您上台", "S05": "你根本不是我"}

    def make(self, **kw):
        shots = kw.pop("shots", [shot("S01"), shot("S02", role="PAYOFF"), shot("S03", target=4),
                                 shot("S04", target=2.0), shot("S05")])
        return episode(self.UNITS, lines=self.LINES, shots=shots, **kw)

    def test_silent_units_cut_dialogue_untouched(self) -> None:
        contract, grouping, report = self.make()
        speaking_before = {u: (row(report, u)["after_in"], row(report, u)["after_out"]) for u in ("VU-001", "VU-002",
                                                                                                  "VU-005")}
        motion = {"VU-003": motion_peak_at(3.0), "VU-004": [0.4] * 100}
        out = pc.apply_peak_windows(report, contract, grouping, motion, runtime_floor_seconds=0.0)
        self.assertEqual(out["status"], "APPLIED")
        r3, r4 = row(report, "VU-003"), row(report, "VU-004")
        # VU-003 follows the PAYOFF shot: a reaction, 1.5-2.5 s around its peak
        self.assertEqual((r3["reasons"], r3["beat_role"]), (["PEAK_WINDOW"], "REACTION"))
        self.assertAlmostEqual(r3["after_out"] - r3["after_in"], 2.5, places=3)
        self.assertGreater(r3["after_in"], 0.0)
        # VU-004: an ordinary silent shot authored at 2 s with a flat take keeps its head
        self.assertEqual((r4["reasons"], r4["after_in"], r4["after_out"]), (["HEAD_WINDOW"], 0.0, 2.0))
        for uid, window in speaking_before.items():
            self.assertEqual((row(report, uid)["after_in"], row(report, uid)["after_out"]), window, uid)
            self.assertNotIn("PEAK_WINDOW", row(report, uid)["reasons"])
        self.assertEqual(report["after_total_seconds"],
                         round(sum(r["after_out"] - r["after_in"] for r in report["units"]), 3))
        # merge writes the window into the build inputs; the silent unit's ASR is dropped
        tail = {"units": [{"unit_id": u, "trimmed": False} for u, _ in self.UNITS]}
        head = {"units": [{"unit_id": u, "trimmed": False} for u, _ in self.UNITS]}
        tail, head = pc.merge(tail, head, report)
        cut = pc.windows(tail, head, {u: 4.458 for u, _ in self.UNITS})
        self.assertEqual(cut["VU-003"], (r3["after_in"], r3["after_out"]))
        self.assertEqual(cut["VU-004"], (0.0, 2.0))

    def test_runtime_floor_trims_less_and_never_below(self) -> None:
        contract, grouping, report = self.make()
        total = report["after_total_seconds"]
        planned = sum(c["current"] - c["length"] for c in pc.peak_candidates(report, contract, grouping))
        floor = round(total - planned / 2, 3)
        out = pc.apply_peak_windows(report, contract, grouping, {}, runtime_floor_seconds=floor)
        self.assertAlmostEqual(out["scale"], 0.5, places=3)
        self.assertGreaterEqual(report["after_total_seconds"] + 1e-6, floor)
        self.assertAlmostEqual(report["after_total_seconds"], floor, places=2)
        # already at/under the floor: nothing is cut
        contract, grouping, report = self.make()
        before = report["after_total_seconds"]
        out = pc.apply_peak_windows(report, contract, grouping, {}, runtime_floor_seconds=before + 5)
        self.assertEqual(out["status"], "RUNTIME_FLOOR")
        self.assertEqual(report["after_total_seconds"], before)
        self.assertFalse(any("PEAK_WINDOW" in r["reasons"] or "HEAD_WINDOW" in r["reasons"]
                             for r in report["units"]))

    def test_last_unit_vo_unit_multishot_and_bridge_guard(self) -> None:
        units = [("VU-001", ["S01"]), ("VU-002", ["S02", "S03"]), ("VU-003", ["S04"]), ("VU-004", ["S05"]),
                 ("VU-005", ["S06"])]
        shots = [shot("S01"), shot("S02"), shot("S03"), shot("S04", role="REACTION", bridge=2.0), shot("S05"),
                 shot("S06")]
        contract, grouping, report = episode(units, lines={"S01": "钱呢花了给谁"}, shots=shots,
                                             vo={"VU-004": [1.2]})
        cands = {c["unit_id"]: c for c in pc.peak_candidates(report, contract, grouping)}
        self.assertNotIn("VU-002", cands)    # multi-shot unit: a continuous action
        self.assertNotIn("VU-004", cands)    # carries V.O.
        self.assertNotIn("VU-005", cands)    # the episode's last unit (cliffhanger)
        self.assertEqual(cands["VU-003"]["length"], 2.5)   # bridged 2.0 s line + 0.5, not the 1.5-2.5 clamp below

    def test_vo_cascade_into_dialogue_reverts(self) -> None:
        units = [("VU-001", ["S01"]), ("VU-002", ["S02"]), ("VU-003", ["S03"]), ("VU-004", ["S04"])]
        # 8 s of narration from VU-001 fits before VU-003's line only while VU-002 keeps its whole take
        contract, grouping, report = episode(units, lines={"S03": "门开了"}, vo={"VU-001": [8.0]})
        self.assertTrue(pc._vo_fits(report["units"], {"VU-003": row(report, "VU-003")}))
        out = pc.apply_peak_windows(report, contract, grouping, {}, runtime_floor_seconds=0.0)
        self.assertEqual(out["status"], "REVERTED_VO_CASCADE")
        self.assertEqual(row(report, "VU-002")["reasons"], [])

    def test_disabled_by_env_or_contract(self) -> None:
        self.assertFalse(pc.peak_trim_enabled({}, {pc.PEAK_TRIM_ENV: "off"}))
        self.assertFalse(pc.peak_trim_enabled({"s7_peak_trim": "OFF"}, {}))
        self.assertTrue(pc.peak_trim_enabled({}, {}))
        contract, grouping, report = self.make()
        before = json.dumps(report, sort_keys=True)
        out = pc.apply_peak_windows(report, contract, grouping, {}, enabled=False)
        self.assertEqual(out["status"], "DISABLED")
        report.pop("peak_trim")
        self.assertEqual(json.dumps(report, sort_keys=True), before)
        self.assertEqual(pc.runtime_floor_ratio({}), pc.RUNTIME_FLOOR_RATIO)
        self.assertEqual(pc.runtime_floor_ratio({pc.PEAK_TRIM_RUNTIME_FLOOR_ENV: "0.8"}), 0.8)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_real_clip_motion_is_measured_and_the_peak_found(self) -> None:
        import nalu_pipeline as npl
        clip = Path(tempfile.mkdtemp()) / "E03-VU-003.mp4"
        # 4.5 s dark take; a bright square sweeps across it between 2.9 s and 3.4 s (the action beat)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=180x320:r=24:d=4.5",
                        "-f", "lavfi", "-i", "color=c=white:s=60x60:r=24:d=4.5", "-filter_complex",
                        "[0][1]overlay=x='(t-2.9)*240':y=120:enable='between(t,2.9,3.4)'",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
        motion = npl._unit_motion_energy(clip)
        self.assertGreater(len(motion), 90)
        win = pc.peak_window(motion, 4.5, 2.5)
        self.assertEqual(win["signal"], "PEAK")
        self.assertTrue(2.8 <= win["peak_at"] <= 3.5, win)
        self.assertLessEqual(win["start"], 2.9)                   # the whole beat is inside the kept 2.5 s
        self.assertGreaterEqual(win["end"], 3.4)
        self.assertIsNone(npl._unit_motion_energy(clip.with_name("missing.mp4")))

    def test_pipeline_wires_it_inside_the_performance_cut_step(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def s7_dialogue_tail_trim"):src.index("def s7_measured_edit_yield_to_performance_cut")]
        self.assertLess(body.index("_perf.plan("), body.index("s7_peak_window_trim("))
        self.assertLess(body.index("s7_peak_window_trim("), body.index("_perf.merge(report, head, perf)"))
        helper = src[src.index("def s7_peak_window_trim"):src.index("def s7_dialogue_tail_trim")]
        self.assertIn("runtime_floor_seconds=floor", helper)
        self.assertIn("except Exception", helper)


# --------------------------------------------------------------------------- pacing metrics
class PacingMetricsTest(unittest.TestCase):
    def test_measured_from_shot_windows_and_asr(self) -> None:
        shots = [{"shot_index": 0, "start_seconds": 0.0, "end_seconds": 2.0},
                 {"shot_index": 1, "start_seconds": 2.0, "end_seconds": 8.5},
                 {"shot_index": 2, "start_seconds": 8.5, "end_seconds": 11.0},
                 {"shot_index": 3, "start_seconds": 11.0, "end_seconds": 16.0}]
        asr = [{"start": 0.2, "end": 1.8, "text": "x"}, {"start": 11.5, "end": 15.0, "text": "y"}]
        out = craft.measure_pacing(shots, asr, 16.0)
        self.assertEqual(out["shot_count"], 4)
        self.assertEqual(out["mean_shot_seconds"], 4.0)
        self.assertEqual(out["longest_shot"], {"shot_index": 1, "seconds": 6.5, "at": 2.0})
        self.assertEqual(out["longest_silent_shot"], {"shot_index": 1, "seconds": 6.5, "at": 2.0})
        self.assertEqual(out["silent_shots_over_4s"], [{"shot_index": 1, "seconds": 6.5, "at": 2.0}])
        self.assertEqual((out["first_speech_at"], out["last_speech_end"]), (0.2, 15.0))
        self.assertEqual(out["dialogue_share_ref"], round(5.1 / 16.0, 3))
        self.assertEqual(out["payoff_required"], 0)
        self.assertEqual(craft.measure_pacing(shots, {"segments": asr}, 110.0)["payoff_required"], 4)
        self.assertEqual(craft.measure_pacing([], None, 0)["shot_count"], 0)


# --------------------------------------------------------------------------- lenient parse
GOOD_BLOCK = {
    "standard_version": "NALU_CRAFT_STANDARD_v1",
    "layer_scores": {"pacing_structure": {"score": 3, "core_pass": "5/8", "reason": "爽点间隔过大，中段 33 s 无翻转"},
                     "clarity_grammar": {"score": "4", "core_pass": "12/13", "reason": "正反打清楚，轴线稳定"}},
    "items": {"S-01": {"verdict": "PASS", "evidence": "0.6 s 泼酒"}, "S-02": {"verdict": "gap", "evidence": "38-71 s"},
              "S-03": {"verdict": "GAP", "evidence": "shot 14 停 6.1 s"}, "C-07": {"verdict": "NA"}},
    "top_gaps": [{"rank": 2, "item_id": "S03", "shot_index": 1, "at_seconds": 52.0, "metric": "无台词停 6.1 s",
                  "fix": "改写成 2 s、动作从第 0 帧开始", "fix_owner": "s7"},
                 {"rank": 1, "item_id": "S-02", "window": [38.0, 71.0], "metric": "33 s 无爽点（上限 25 s）",
                  "fix": "把 71 s 的揭示前移到约 50 s", "fix_owner": "writer"}],
    "pacing_metrics": {"first_conflict_at": 0.6, "cliffhanger_at": 106.9,
                       "payoffs": [{"t": 71.0, "type": "身份揭示", "setup_t": 52.3, "reaction_shot": 21},
                                   {"t": 14.2, "type": "打脸", "setup_t": 6.0}]},
}


class ParseBlockTest(unittest.TestCase):
    def test_missing_and_malformed_blocks_never_raise(self) -> None:
        self.assertEqual(craft.parse_block(None, standard=STANDARD)["status"], "MISSING")
        self.assertEqual(craft.parse_block("great film", standard=STANDARD)["status"], "MALFORMED")
        out = craft.parse_block({"items": "all pass", "top_gaps": {"x": 1}, "layer_scores": {"pacing_structure": 9},
                                 "pacing_metrics": {"first_conflict_at": "soon", "payoffs": [None, {"t": -3}]}},
                                standard=STANDARD, duration=110.0)
        self.assertEqual(out["status"], "PARTIAL")
        self.assertEqual((out["items"], out["top_gaps"], out["layer_scores"]), ({}, [], {}))
        self.assertIn("items:not_object", out["notes"])
        self.assertIn("pacing_metrics.first_conflict_at:invalid", out["notes"])

    def test_good_block_is_normalised(self) -> None:
        out = craft.parse_block(GOOD_BLOCK, standard=STANDARD, duration=110.0, shot_count=40,
                                measured={"mean_shot_seconds": 3.6})
        self.assertEqual(out["layer_scores"]["pacing_structure"]["score"], 3)
        self.assertEqual(out["layer_scores"]["clarity_grammar"]["score"], 4)
        self.assertEqual(out["items"]["S-02"]["verdict"], "GAP")
        self.assertEqual([g["item_id"] for g in out["top_gaps"]], ["S-02", "S-03"])   # by rank
        self.assertEqual(out["top_gaps"][1]["fix_owner"], "S7")
        self.assertEqual(out["top_gaps"][0]["window"], [38.0, 71.0])
        self.assertEqual(out["core_pass"]["pacing_structure"], {"pass": 1, "gap": 2, "judged": 3, "core_items": 8})
        self.assertEqual([p["t"] for p in out["pacing_metrics"]["payoffs"]], [14.2, 71.0])
        self.assertEqual(out["pacing_metrics"]["max_payoff_gap_seconds"], 56.8)
        self.assertEqual(out["measured_pacing"], {"mean_shot_seconds": 3.6})

    def test_bad_rows_are_dropped_with_notes(self) -> None:
        block = json.loads(json.dumps(GOOD_BLOCK))
        block["items"]["Z-99"] = {"verdict": "PASS"}
        block["items"]["S-04"] = {"verdict": "MAYBE"}
        block["top_gaps"] += [{"item_id": "X-1", "fix": "x"}, "nope", {"item_id": "C-05", "fix_owner": "director",
                                                                         "shot_index": 999, "at_seconds": 500}]
        out = craft.parse_block(block, standard=STANDARD, duration=110.0, shot_count=40)
        self.assertNotIn("Z-99", out["items"])
        self.assertNotIn("S-04", out["items"])
        self.assertEqual(len(out["top_gaps"]), 3)
        c05 = next(g for g in out["top_gaps"] if g["item_id"] == "C-05")
        self.assertEqual(c05["fix_owner"], "writer")            # unknown owner -> the item's default
        self.assertNotIn("shot_index", c05)
        self.assertNotIn("at_seconds", c05)
        for note in ("items:unknown_id:Z-99", "items.S-04:invalid_verdict", "top_gaps.2:unknown_item_id",
                     "top_gaps.3:not_object", "top_gaps.4:fix_owner_defaulted:writer"):
            self.assertIn(note, out["notes"])


class FinalReviewLeniencyTest(unittest.TestCase):
    """The block rides on a real submit: request carries it, the review outcome never depends on it."""

    def setUp(self) -> None:
        from tools.tests import test_nalu_final_audience_review as base
        self.base = base
        self.case = base.FinalAudienceReviewTests("test_valid_independent_review_materialises_reports_and_passes_both_gates")
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.case._prepare()
        self.request = json.loads(self.case.request.read_text(encoding="utf-8"))
        self.craft_file = self.case.root / "E01_CRAFT_STANDARD.json"

    def test_request_carries_core_items_and_measured_pacing(self) -> None:
        req = self.request["craft_standard_request"]
        self.assertEqual(req["standard_version"], craft.STANDARD_VERSION)
        self.assertEqual(len(req["items"]), 26)
        self.assertEqual(req["measured_pacing"]["shot_count"], 2)
        self.assertEqual(req["measured_pacing"]["mean_shot_seconds"], 6.0)
        self.assertIn("craft_standard", self.request["answer_contract"])

    def test_missing_malformed_and_valid_blocks_give_the_same_verdict(self) -> None:
        outcomes = []
        for block in (None, "garbage", {"top_gaps": [{"item_id": "nope"}]}, GOOD_BLOCK):
            answers = self.case._answers()
            if block is not None:
                answers["craft_standard"] = block
            code, result = self.case._submit(answers)
            outcomes.append((code, result["status"], result["verdict"]))
            if block is None:
                self.assertNotIn("craft_standard", result)
                self.assertFalse(self.craft_file.exists())
            else:
                self.assertEqual(result["craft_standard"]["authority"], "ADVISORY_NOT_A_GATE")
                self.assertTrue(self.craft_file.is_file())
        self.assertEqual(set(outcomes), {(0, "PASS", "PASS")})
        saved = json.loads(self.craft_file.read_text(encoding="utf-8"))
        self.assertEqual([g["item_id"] for g in saved["top_gaps"]], ["S-02", "S-03"])
        self.assertNotIn("window", saved["top_gaps"][0])      # 38-71 s lies outside this 12 s cut: dropped, gap kept
        self.assertNotIn("at_seconds", saved["top_gaps"][1])
        self.assertEqual(saved["bindings"]["final_video_sha256"], self.request["media"]["sha256"])


# --------------------------------------------------------------------------- gap -> knowledge events
class GapEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        import knowledge_event_log as kel
        import nalu_knowledge_events as kev
        self.kel, self.kev = kel, kev
        self.rt = Path(tempfile.mkdtemp()) / "runtime"
        (self.rt / "reports").mkdir(parents=True)
        self.craft_path = self.rt / "E04_CRAFT_STANDARD.json"

    def write(self, gaps) -> None:
        block = {"top_gaps": gaps, "items": {g["item_id"]: {"verdict": "GAP"} for g in gaps if "item_id" in g}}
        parsed = craft.parse_block(block, standard=STANDARD, duration=110.0, shot_count=40,
                                   measured={"mean_shot_seconds": 3.7, "shot_count": 30, "duration_seconds": 110.0,
                                             "longest_silent_shot": {"shot_index": 9, "seconds": 6.1, "at": 52.0}})
        parsed["bindings"] = {"final_video_sha256": "a" * 64}
        self.craft_path.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")

    def record(self, **kw):
        return self.kev.record_craft_gaps(self.rt, episode="E04", craft_path=str(self.craft_path),
                                          media_sha256="b" * 64, language="zh",
                                          cast_names=[("CHAR-SHEN", "沈棠"), ("CHAR-ZHAO", "赵干")],
                                          dialogue_lines=["沈棠：你根本不是我的未婚夫", "赵干：钱呢？"], **kw)

    def rows(self):
        return [r for r in self.kel.events(self.rt, episode="E04")
                if (r.get("evidence") or {}).get("failure_type") == craft.FAILURE_TYPE]

    def test_cluster_key_stage_and_scrub(self) -> None:
        self.write([
            {"rank": 1, "item_id": "S-03", "shot_index": 9, "at_seconds": 52.0, "metric": "无台词停 6.1 s（上限 4 s）",
             "fix": "沈棠回头那一镜改成 2 s，动作从第 0 帧开始", "fix_owner": "S7"},
            {"rank": 2, "item_id": "S-06", "at_seconds": 104.0, "metric": "揭示后又拖 4 s",
             "fix": "结尾停在「你根本不是我的未婚夫」这句上", "fix_owner": "writer"},
            {"rank": 3, "item_id": "S-08", "metric": "超长句 5 句",
             "fix": "把你根本不是我的未婚夫拆成两句", "fix_owner": "writer"}])
        out = self.record()
        self.assertEqual(out["status"], "OK", out)
        rows = {r["evidence"]["item"]: r for r in self.rows()}
        self.assertEqual(set(rows), {"S-03", "S-06", "S-08"})
        s03, s06, s08 = rows["S-03"], rows["S-06"], rows["S-08"]
        self.assertEqual(s03["evidence"]["cluster_key"], "CRAFT_STD_GAP|S-03")
        self.assertEqual((s03["stage"], s06["stage"]), ("STORYBOARD_AUTHORING", "SCRIPT_AUTHORING"))
        self.assertEqual(s03["evidence"]["detail"]["metric_values"], [6.1, 4.0])
        self.assertEqual(s03["evidence"]["detail"]["measured_pacing"]["longest_silent_shot_seconds"], 6.1)
        self.assertEqual(s03["evidence"]["detail"]["fix"], "角色A回头那一镜改成 2 s，动作从第 0 帧开始")
        self.assertEqual(s06["evidence"]["detail"]["fix"], "结尾停在「…」这句上")          # quoted line removed
        self.assertNotIn("fix", s08["evidence"]["detail"])                              # unquoted dialogue run
        blob = json.dumps([r["evidence"] for r in rows.values()] + [r["symptom"] for r in rows.values()],
                          ensure_ascii=False)
        for secret in ("沈棠", "赵干", "未婚夫", "钱呢"):
            self.assertNotIn(secret, blob)
        from tools.collective_learning import contracts as c
        self.assertEqual(c.sensitive_findings([r["evidence"] for r in rows.values()]), [])
        # the collector clusters them by item id and treats them as lessons (default thresholds apply)
        from tools.collective_learning import release_train as rt_mod
        self.assertEqual(rt_mod.cluster_key({**s03, "event_kind": "FAILURE_OBSERVATION"}), "CRAFT_STD_GAP|S-03")
        self.assertTrue(rt_mod.is_lesson({**s03, "event_kind": "FAILURE_OBSERVATION"}))
        sample = rt_mod.evidence_sample(s03)
        self.assertEqual((sample["item"], sample["detail"]["fix_owner"]), ("S-03", "S7"))
        # re-entry is deduplicated per item and cut
        again = self.record()
        self.assertTrue(all(e["status"] == "DUPLICATE" for e in again["events"]))

    def test_sensitive_fix_is_dropped_and_no_block_is_quiet(self) -> None:
        self.write([{"item_id": "C-04", "metric": "3 人同框", "fix_owner": "engine",
                     "fix": "see https://example.com/x api_key=abcdefgh12345678"}])
        self.record()
        (row,) = self.rows()
        self.assertNotIn("fix", row["evidence"]["detail"])
        self.assertNotIn("example.com", json.dumps(row, ensure_ascii=False))
        self.craft_path.unlink()
        self.assertEqual(self.record()["status"], "NO_CRAFT_STANDARD_BLOCK")

    def test_release_train_review_instructions_name_the_carrier(self) -> None:
        text = (ROOT / "tools/collective_learning/release_train.py").read_text(encoding="utf-8")
        self.assertIn("CRAFT_STD_GAP|<item id>", text)
        self.assertIn("DIRECTING_GUIDANCE rule", text)
        from tools.collective_learning import release_train as rt_mod
        self.assertEqual((rt_mod.DEFAULTS["min_devices"], rt_mod.DEFAULTS["min_episodes"],
                          rt_mod.DEFAULTS["lookback_days"]), (3, 5, 30))   # default promotion thresholds


if __name__ == "__main__":
    unittest.main()
