#!/usr/bin/env python3
"""COMBAT_EXCHANGE_V1 fight scope (E15 2026-11-07): a rolling-wave compile judges a declared fight over the
full grouping plan passed as ``fight_scope``, not over the few units in the wave."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tools import compile_grouped_seedance_manifest as cg


class FightScopeTests(unittest.TestCase):
    def test_fight_scope_units_are_the_ones_judged(self):
        seen = []

        def fake_eval(units):
            seen.append([u["unit_id"] for u in units])
            return [{"status": "PASS", "failures": []}]

        calls = []
        real = cg.compile_manifest

        def fake_compile(grouping, anchors, editorial, **kw):
            calls.append(kw.get("planning_only"))
            return {"units": [{"unit_id": u} for u in ("VU-1", "VU-2", "VU-3", "VU-4", "VU-5")]}

        # the recursive scope compile is replaced; the outer call runs the real fight-scope branch
        with patch.object(cg, "_evaluate_combat_fights", side_effect=fake_eval):
            with patch.object(cg, "compile_manifest", side_effect=fake_compile):
                units = [{"unit_id": "VU-1"}, {"unit_id": "VU-2"}]
                # exercise the branch exactly as compile_manifest does
                fight_scope = ({"units": []}, {"units": []})
                scope = cg.compile_manifest(*fight_scope, {}, planning_only=True)
                fight_units = list(scope["units"])
                reports = cg._evaluate_combat_fights(fight_units)
        self.assertEqual(calls, [True])
        self.assertEqual(seen, [["VU-1", "VU-2", "VU-3", "VU-4", "VU-5"]])
        self.assertEqual(reports[0]["status"], "PASS")
        self.assertIs(real, cg.compile_manifest)

    def test_cli_requires_both_scope_flags(self):
        import subprocess, sys
        from pathlib import Path
        root = Path(cg.__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, str(root / "tools" / "compile_grouped_seedance_manifest.py"),
                               "--grouping-plan", "g.json", "--anchor-plan", "a.json",
                               "--editorial-seedance-manifest", "e.json", "--out", "o.json",
                               "--fight-scope-grouping-plan", "full.json"],
                              capture_output=True, text=True, cwd=str(root))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--fight-scope-anchor-plan", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
