#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/manifest_self_limit_and_version_assert.py 的测试。授权 CL2X-1290 seq=47 c1/c2。"""
import json
import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import manifest_self_limit_and_version_assert as M  # noqa: E402


def _write(tmp, ep, ver, manifest, contract_version="same"):
    mp = os.path.join(tmp, f"E{ep}_manifest_v{ver}.json")
    json.dump(manifest, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
    cv = ver if contract_version == "same" else contract_version
    if cv is not None:
        cp = os.path.join(tmp, f"E{ep}_GENERATION_CONTRACT_v{ver}.json")
        json.dump({"version": cv}, open(cp, "w", encoding="utf-8"))
    return mp


class TestSelfLimit(unittest.TestCase):
    def test_looser_than_registered_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 1, {"version": 1, "event_density": {
                "max_information_gap_seconds": 18.0,
                "★rulers": {"cross_scene_silence_seconds": 29.3,
                            "self_limit_cross_scene": 30.0}}})
            r = M.evaluate(mp)
            self.assertEqual(r["verdict"], "BLOCK")
            self.assertEqual(r["self_limit_findings"][0]["verdict"],
                             "BLOCK_SELF_LIMIT_LOOSER_THAN_REGISTERED_THRESHOLD")
            self.assertEqual(r["self_limit_findings"][0]["limit_id"],
                             "MAX_INFORMATION_GAP_SECONDS")
            with self.assertRaises(M.SelfLimitViolation):
                M.assert_manifest_ok(mp)

    def test_equal_and_tighter_pass(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 1, {"version": 1,
                                   "event_density": {"★r": {"in_scene_silence_seconds": 18.5,
                                                            "self_limit_in_scene": 20.0}},
                                   "dialogue_pacing": {"dialogue_ratio": 0.19,
                                                       "self_limit_this_episode": 0.33}})
            r = M.evaluate(mp)
            self.assertEqual(r["verdict"], "PASS", r)
            self.assertEqual(len(r["self_limit_ok"]), 2)

    def test_min_bound_self_limit_lower_is_looser(self):
        """下界门限：自限比门限更低 = 更宽 = 阻断。"""
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 1, {"version": 1, "event_density": {
                "story_moves_per_minute": 4.0, "self_limit_story_moves": 2.0}})
            r = M.evaluate(mp)
            self.assertEqual(r["verdict"], "BLOCK")
            self.assertEqual(r["self_limit_findings"][0]["limit_id"],
                             "MIN_STORY_MOVES_PER_MINUTE")

    def test_unmapped_self_limit_blocks_unless_declared(self):
        """改个名字绕开门限这条路必须堵死。"""
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 1, {"version": 1, "★zone": {"self_limit_mystery": 99.0}})
            self.assertEqual(M.evaluate(mp)["self_limit_findings"][0]["verdict"],
                             "BLOCK_UNMAPPED_SELF_LIMIT")
            mp2 = _write(t, 52, 1, {"version": 1, "★zone": {
                "self_limit_mystery": 99.0,
                "★self_limit_registry_ref": "NO_REGISTERED_COUNTERPART：纯写手诊断量，无注册门对应物"}})
            self.assertEqual(M.evaluate(mp2)["verdict"], "PASS")

    def test_text_self_limit_notes_are_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 1, {"version": 1,
                                   "dialogue_pacing": {"★self_limit_note": "说明文字，不是数值"}})
            self.assertEqual(M.evaluate(mp)["verdict"], "PASS")


class TestVersionTriple(unittest.TestCase):
    def test_manifest_version_ne_filename_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 5, {"version": 4})
            r = M.evaluate(mp)
            self.assertEqual(r["verdict"], "BLOCK")
            self.assertEqual(r["version_findings"][0]["verdict"],
                             "BLOCK_MANIFEST_VERSION_NE_FILENAME")

    def test_contract_version_ne_filename_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 5, {"version": 5}, contract_version=4)
            self.assertEqual(M.evaluate(mp)["version_findings"][0]["verdict"],
                             "BLOCK_CONTRACT_VERSION_NE_FILENAME")

    def test_missing_contract_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 5, {"version": 5}, contract_version=None)
            self.assertEqual(M.evaluate(mp)["version_findings"][0]["verdict"],
                             "BLOCK_GENERATION_CONTRACT_MISSING")

    def test_all_three_match_passes(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 5, {"version": 5})
            self.assertEqual(M.evaluate(mp)["verdict"], "PASS")


class TestScopeAndDrift(unittest.TestCase):
    def test_e50_and_earlier_is_diagnostic_only(self):
        """seq=47 明写不回头改 E50 v5 字节 ⇒ E50 及以前不得阻断。"""
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 50, 5, {"version": 4, "event_density": {
                "★r": {"cross_scene_silence_seconds": 18.8,
                       "self_limit_cross_scene_this_episode": 30.0}}})
            r = M.evaluate(mp)
            self.assertEqual(r["verdict"], "DIAGNOSTIC_ONLY_WOULD_BLOCK")
            self.assertFalse(r["in_force"])
            M.assert_manifest_ok(mp)  # 不抛异常

    def test_limit_table_drift_guard_fires(self):
        original = M.REGISTERED_LIMITS["MAX_INFORMATION_GAP_SECONDS"]["probe"]
        M.REGISTERED_LIMITS["MAX_INFORMATION_GAP_SECONDS"]["probe"] = "if max_gap > 999999:"
        try:
            with self.assertRaises(M.SelfLimitViolation) as cm:
                M.check_self_limits({})
            self.assertIn("REGISTERED_LIMIT_TABLE_DRIFTED", str(cm.exception))
        finally:
            M.REGISTERED_LIMITS["MAX_INFORMATION_GAP_SECONDS"]["probe"] = original

    def test_live_table_matches_live_gate_source(self):
        """本表是注册门的只读镜像：全部 probe 必须在门源码里逐字存在。"""
        M.check_self_limits({})


class TestRealE50V5(unittest.TestCase):
    def test_real_e50_v5_reproduces_the_two_findings_the_supervisor_named(self):
        p = os.path.join(M.REPO_ROOT, "workflow", "claude_writer_agent", "scripts",
                         "E50_manifest_v5.json")
        if not os.path.exists(p):
            self.skipTest("E50_manifest_v5.json 不在本挂载上")
        r = M.evaluate(p)
        self.assertEqual(r["verdict"], "DIAGNOSTIC_ONLY_WOULD_BLOCK")
        self.assertEqual([f["verdict"] for f in r["self_limit_findings"]],
                         ["BLOCK_SELF_LIMIT_LOOSER_THAN_REGISTERED_THRESHOLD"])
        self.assertEqual(r["self_limit_findings"][0]["value"], 30.0)
        self.assertEqual([f["verdict"] for f in r["version_findings"]],
                         ["BLOCK_MANIFEST_VERSION_NE_FILENAME"])
        self.assertEqual(r["version_findings"][0]["manifest_version"], 4)




class TestScanModeAndVersionForms(unittest.TestCase):
    def test_scan_mode_never_enforces(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 77, 2, {"version": "v2"}, contract_version=None)
            self.assertEqual(M.evaluate(mp, enforcing=False)["verdict"],
                             "DIAGNOSTIC_ONLY_WOULD_BLOCK")
            self.assertEqual(M.evaluate(mp, enforcing=True)["verdict"], "BLOCK")

    def test_string_version_forms_accepted_with_warning(self):
        with tempfile.TemporaryDirectory() as t:
            mp = _write(t, 51, 2, {"version": "v2"}, contract_version="v2")
            r = M.evaluate(mp)
            self.assertEqual(r["verdict"], "PASS")
            self.assertEqual([f["verdict"] for f in r["version_findings"]],
                             ["WARN_MANIFEST_VERSION_NOT_AN_INTEGER"])

    def test_real_e49_v5_contract_self_identifies_as_v4(self):
        """R416 头号发现：E49 v5 的 manifest 与 generation contract 都自称 v4。"""
        d = os.path.join(M.REPO_ROOT, "workflow", "claude_writer_agent", "scripts")
        mp = os.path.join(d, "E49_manifest_v5.json")
        if not os.path.exists(mp):
            self.skipTest("E49_manifest_v5.json 不在本挂载上")
        r = M.evaluate(mp)
        verdicts = [f["verdict"] for f in r["version_findings"]]
        self.assertIn("BLOCK_MANIFEST_VERSION_NE_FILENAME", verdicts)
        self.assertIn("BLOCK_CONTRACT_VERSION_NE_FILENAME", verdicts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
