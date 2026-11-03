"""Q2 index: an item-restricted review keeps the other units' admitted rows (E12 2026-10-31)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import video_q2_builder as vqb  # noqa: E402


class PartialIndexTests(unittest.TestCase):
    def test_unreviewed_units_carry_forward_only_while_media_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = {uid: root / f"{uid}.mp4" for uid in ("A", "B", "C", "D")}
            for uid, path in media.items():
                path.write_bytes(uid.encode())
            sha = {uid: hashlib.sha256(uid.encode()).hexdigest() for uid in media}
            previous = {"results": [
                {"unit_id": "A", "asset_sha256": sha["A"], "downstream_status": vqb.TERMINAL_DOWNSTREAM},
                {"unit_id": "B", "asset_sha256": sha["B"], "downstream_status": vqb.TERMINAL_DOWNSTREAM},
                {"unit_id": "C", "asset_sha256": "0" * 64, "downstream_status": vqb.TERMINAL_DOWNSTREAM},
            ]}
            (root / "E_TEST_VIDEO_Q2_INDEX.json").write_text(json.dumps(previous), encoding="utf-8")
            exp = SimpleNamespace(video_unit_items=lambda: [{"unit_id": u} for u in ("A", "B", "C", "D")])
            paths = SimpleNamespace(q2_dir=root)
            with mock.patch.object(vqb, "unit_media", lambda episode, uid: media[uid]):
                carried, dropped = vqb.carry_forward_rows("E_TEST", [{"unit_id": "B"}], exp, paths)
            # A unchanged -> kept; B reviewed now -> not duplicated; C take changed -> dropped;
            # D never indexed -> neither (the episode status still counts it as missing upstream).
            self.assertEqual([row["unit_id"] for row in carried], ["A"])
            self.assertEqual(dropped, ["C"])

    def test_materialise_merges_carried_rows_before_the_status(self):
        source = (ROOT / "lines/nalu/runtime/tools/video_q2_builder.py").read_text(encoding="utf-8")
        body = source[source.index("def materialise("):source.index("def route_status(")]
        self.assertLess(body.index("carry_forward_rows("), body.index('"status": ("ALL_ADMITTED"'))


if __name__ == "__main__":
    unittest.main()
