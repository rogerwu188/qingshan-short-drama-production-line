"""Q1 still-image OCR runs per keyframe in parallel, one report file per item.

The S5 Q1 materialisation ran the engine's OCR subprocess once per keyframe in a
serial item loop.  Model startup dominates each call, so a keyframe set paid that
startup N times.  Items are independent, with one trap: a video unit can carry
more than one keyframe, and the legacy output name is per unit, so two items of
one unit would otherwise race the same ``ocr_audit.json``.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import keyframe_q1_builder as q1  # noqa: E402


def _item(item_id: str, unit_id: str, asset: Path) -> dict:
    return {
        "item_id": item_id,
        "request_item": {
            "unit_id": unit_id,
            "media": [{"role": "KEYFRAME", "path": str(asset)}],
        },
    }


class OcrKeyframesConcurrencyTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.assets = self.root / "assets"
        self.assets.mkdir()
        self.q1_dir = self.root / "q1"

    def _asset(self, name: str) -> Path:
        path = self.assets / f"{name}.png"
        path.write_bytes(b"png")
        return path

    def _run(self, items, fake_run_ocr, *, env=None, workers=None):
        keyframes = {item["item_id"]: Path(item["request_item"]["media"][0]["path"])
                     for item in items}
        with mock.patch.dict("os.environ", env or {}), \
             mock.patch.object(q1, "run_ocr", fake_run_ocr):
            return q1.ocr_keyframes(items, keyframes, ["FORBIDDEN"], self.q1_dir,
                                    workers=workers)

    def test_stills_are_scanned_concurrently(self):
        items = [_item(f"S{i}-01", f"U{i}", self._asset(f"a{i}")) for i in range(4)]
        barrier = threading.Barrier(4, timeout=4.0)

        def fake(asset, _terms, out):
            barrier.wait()  # a serial loop deadlocks here and fails the test
            return {"exit_code": 0, "report": {"status": "PASS"}, "report_path": str(out)}

        results = self._run(items, fake, env={"NALU_Q1_OCR_WORKERS": "4"})
        self.assertEqual(sorted(results), [item["item_id"] for item in items])

    def test_two_items_in_one_unit_write_distinct_reports(self):
        asset_a, asset_b = self._asset("a"), self._asset("b")
        items = [_item("S01-01", "U1", asset_a), _item("S01-05", "U1", asset_b)]
        written: list[str] = []

        def fake(_asset_path, _terms, out):
            written.append(Path(out).name)
            return {"exit_code": 0, "report": {}, "report_path": str(out)}

        self._run(items, fake, env={"NALU_Q1_OCR_WORKERS": "2"})

        self.assertEqual(len(set(written)), 2,
                         "SAME_UNIT_OCR_REPORT_COLLISION: two keyframes of one unit wrote "
                         f"the same report file: {written}")
        self.assertIn("ocr_audit.json", written, "the first item must keep the legacy name so "
                                                "exact-input caches still hit")

    def test_results_are_keyed_by_item_id(self):
        items = [_item("S07-03", "U7", self._asset("a"))]

        def fake(_asset_path, _terms, out):
            return {"exit_code": 0, "report": {"status": "PASS"}, "report_path": str(out)}

        results = self._run(items, fake)
        self.assertEqual(list(results), ["S07-03"])

    def test_a_missing_asset_is_skipped_not_reported(self):
        items = [_item("S01-01", "U1", self.assets / "absent.png")]

        def fake(*_args, **_kwargs):  # pragma: no cover - must never run
            raise AssertionError("OCR ran for a keyframe that does not exist")

        self.assertEqual(self._run(items, fake), {})

    def test_a_sample_of_missing_and_present_items_scans_only_the_present_ones(self):
        present = self._asset("a")
        items = [_item("S01-01", "U1", present),
                 _item("S02-01", "U2", self.assets / "absent.png")]
        scanned: list[str] = []

        def fake(_asset_path, _terms, out):
            scanned.append(Path(out).parent.name)
            return {"exit_code": 0, "report": {}, "report_path": str(out)}

        results = self._run(items, fake, env={"NALU_Q1_OCR_WORKERS": "2"})
        self.assertEqual(list(results), ["S01-01"])
        self.assertEqual(scanned, ["U1"])

    def test_worker_count_defaults_and_honours_the_environment(self):
        items = [_item(f"S{i}-01", f"U{i}", self._asset(f"a{i}")) for i in range(2)]
        seen: list[int] = []

        def fake(_asset_path, _terms, out):
            return {"exit_code": 0, "report": {}, "report_path": str(out)}

        with mock.patch("concurrent.futures.ThreadPoolExecutor") as pool:
            pool.return_value.__enter__.return_value.submit.side_effect = (
                lambda _fn, *a, **k: type("F", (), {"result": lambda _self: None})()
            )
            self._run(items, fake, env={"NALU_Q1_OCR_WORKERS": "3"})
            seen.append(pool.call_args.kwargs.get("max_workers"))
            self._run(items, fake, env={"NALU_Q1_OCR_WORKERS": "not-a-number"})
            seen.append(pool.call_args.kwargs.get("max_workers"))
        self.assertEqual(seen, [2, 2], "3 workers for 2 items, then the default for a bad value")


if __name__ == "__main__":
    unittest.main()
