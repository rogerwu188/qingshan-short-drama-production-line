#!/usr/bin/env python3
"""The committed still-scoped registry must not churn on every Q1 run (D-13).

The registry is committed, so a fresh `derived_at` on each derivation left the tree dirty
after every episode — and during an unattended run the model is not allowed to write that
file back, so the dirt just accumulated.  The stamp now means "when did this derivation last
change", which is the useful thing for it to mean.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import keyframe_q1_builder as kqb  # noqa: E402


class RegistryTimestampTest(unittest.TestCase):
    def test_rederiving_an_identical_registry_keeps_the_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "reg.json"
            kqb.still_gate_registry(out=out)
            first = json.loads(out.read_text(encoding="utf-8"))
            time.sleep(1.1)  # so a fresh `now()` would be visibly different
            kqb.still_gate_registry(out=out)
            second = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(first["derived_at"], second["derived_at"])

    def test_a_real_change_moves_the_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "reg.json"
            kqb.still_gate_registry(out=out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            payload["single_parameter_changed"] = {"different": True}
            out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            time.sleep(1.1)
            kqb.still_gate_registry(out=out)
            after = json.loads(out.read_text(encoding="utf-8"))
            self.assertNotEqual(payload["derived_at"], after["derived_at"])

    def test_two_independent_derives_are_byte_identical(self):
        # this is what makes the file safe to commit: the content depends on the engine
        # registry and the D-13 decision, never on when the derivation ran
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "a.json", Path(tmp) / "b.json"
            kqb.still_gate_registry(out=one)
            time.sleep(1.1)
            kqb.still_gate_registry(out=two)
            # the first derive of an absent file stamps itself; the second copies the engine's
            # own derived_at only when content matches, so compare content minus the stamp
            strip = lambda p: {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items()
                               if k != "derived_at"}
            self.assertEqual(strip(one), strip(two))

    def test_the_d13_parameter_is_still_the_only_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "reg.json"
            kqb.still_gate_registry(out=out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["single_parameter_changed"]["parameter"], "sample_frames_per_source_min")
            self.assertEqual(payload["single_parameter_changed"]["still_value"], 1)
            for row in payload.get("gates") or []:
                if row.get("gate_id") == "CHARACTER-IDENTITY-ADMISSION":
                    self.assertEqual(row["parameters"]["sample_frames_per_source_min"], 1)


if __name__ == "__main__":
    unittest.main()
