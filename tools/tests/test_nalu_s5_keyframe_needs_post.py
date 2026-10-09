"""S5 must not re-POST a keyframe whose current image is already admitted.

The third instance of D-46.  E11 (2026-10-09): 50 keyframes were paid for, harvested and admitted;
a later free rebuild moved every prompt's bytes, and S5 — unlike S6 — had no rule excluding work
that is already done, so the next paid S5 would have re-POSTed all 50 (550 credits) to re-render
images Q1 had just approved.  Only the shot whose admission actually failed needed a POST.
"""
import hashlib
import importlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for _p in (str(TOOLS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class KeyframeNeedsPostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("nalu_pipeline")

    def _ctx(self, keyframes: Path, manifest: Path) -> SimpleNamespace:
        return SimpleNamespace(p=SimpleNamespace(keyframes=keyframes, keyframe_manifest=manifest))

    def _run(self, tmp: str, shots, admitted, files):
        keyframes = Path(tmp) / "keyframes"
        keyframes.mkdir(parents=True, exist_ok=True)
        for name, body in files.items():
            (keyframes / name).write_bytes(body)
        tasks = [{"task_key": f"{shot}-KEYFRAME-V1", "shot_id": shot,
                  "output_contract": {"expected_output_path": f"{shot}-keyframe-v1.png"}}
                 for shot in shots]
        manifest = Path(tmp) / "manifest.json"
        manifest.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        results = []
        for shot, state in admitted.items():
            row = {"item_id": shot, "unit_id": f"VU-{shot}", "status": state}
            if state != "NONE":
                name = f"{shot}-keyframe-v1.png"
                if (keyframes / name).is_file():
                    row["asset_sha256"] = _sha(keyframes / name)
                else:
                    row["asset_sha256"] = "0" * 64
            results.append(row)
        index = {"results": results, "status": "PARTIAL"}
        return self.mod.keyframe_needs_post(self._ctx(keyframes, manifest), index)

    def test_an_admitted_current_image_needs_no_post(self) -> None:
        with TemporaryDirectory() as tmp:
            need, done = self._run(tmp, ["E11-S01-01"], {"E11-S01-01": "ADMITTED"},
                                   {"E11-S01-01-keyframe-v1.png": b"admitted-bytes"})
        self.assertEqual(need, [])
        self.assertEqual(done, ["E11-S01-01-KEYFRAME-V1"])

    def test_a_rejected_image_needs_a_post(self) -> None:
        with TemporaryDirectory() as tmp:
            need, done = self._run(tmp, ["E11-S02-01"], {"E11-S02-01": "FAIL"},
                                   {"E11-S02-01-keyframe-v1.png": b"has-an-ocr-hit"})
        self.assertEqual(need, ["E11-S02-01-KEYFRAME-V1"])
        self.assertEqual(done, [])

    def test_a_shot_with_no_image_needs_a_post(self) -> None:
        with TemporaryDirectory() as tmp:
            need, done = self._run(tmp, ["E11-S03-01"], {"E11-S03-01": "FAIL"}, {})
        self.assertEqual(need, ["E11-S03-01-KEYFRAME-V1"])

    def test_a_line_owner_accepted_keyframe_needs_no_post(self) -> None:
        with TemporaryDirectory() as tmp:
            need, _ = self._run(tmp, ["E11-S05-05"],
                                {"E11-S05-05": "ADMITTED_BY_LINE_OWNER_ORDER"},
                                {"E11-S05-05-keyframe-v1.png": b"accepted"})
        self.assertEqual(need, [])

    def test_an_admitted_image_that_was_later_re_replaced_is_not_done(self) -> None:
        """The admitted sha must be the image on disk now, not some earlier one."""
        with TemporaryDirectory() as tmp:
            keyframes = Path(tmp) / "keyframes"
            keyframes.mkdir(parents=True)
            (keyframes / "E11-S04-01-keyframe-v1.png").write_bytes(b"the-re-render")
            tasks = [{"task_key": "E11-S04-01-KEYFRAME-V1", "shot_id": "E11-S04-01",
                      "output_contract": {"expected_output_path": "E11-S04-01-keyframe-v1.png"}}]
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
            stored = Path(tmp) / "stored.png"
            stored.write_bytes(b"the-old-image-that-was-admitted")
            index = {"results": [{"item_id": "E11-S04-01", "unit_id": "E11-VU-007",
                                  "status": "ADMITTED", "asset_sha256": _sha(stored)}]}
            need, done = self.mod.keyframe_needs_post(self._ctx(keyframes, manifest), index)
        self.assertEqual(need, ["E11-S04-01-KEYFRAME-V1"],
                         "an admitted sha that is not the file on disk must not count as done")
        self.assertEqual(done, [])

    def test_a_shot_the_review_does_not_cover_is_done_when_an_image_exists(self) -> None:
        """Mid-unit keyframes are not Q1's subject; their generation is complete either way."""
        with TemporaryDirectory() as tmp:
            need, done = self._run(tmp, ["E11-S01-04"], {"E11-S01-01": "ADMITTED"},
                                   {"E11-S01-04-keyframe-v1.png": b"generated-earlier"})
        self.assertEqual(need, [])
        self.assertEqual(done, ["E11-S01-04-KEYFRAME-V1"])

    def test_a_shot_the_review_does_not_cover_and_with_no_image_needs_a_post(self) -> None:
        with TemporaryDirectory() as tmp:
            need, done = self._run(tmp, ["E11-S01-04"], {"E11-S01-01": "ADMITTED"}, {})
        self.assertEqual(need, ["E11-S01-04-KEYFRAME-V1"])
        self.assertEqual(done, [])


if __name__ == "__main__":
    unittest.main()
