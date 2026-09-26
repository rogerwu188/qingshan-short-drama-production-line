"""tools/ad_tail_insert.py tests: synthetic content+endcard+ad fixtures via
ffmpeg lavfi (no real footage needed), CLI-subprocess style matching
tools/tests/test_credit_window_isolation.py's house convention.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def _make_clip(path: Path, *, seconds: float, color: str) -> None:
    subprocess.run([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=720x1280:r=24:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(path),
    ], check=True, capture_output=True)


def _duration(path: Path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class AdTailInsertCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # content = 4s "story" (red) + 3s "endcard" (blue), concatenated as one file,
        # exactly mirroring how p.final_mp4 already has the end-card baked in.
        story = self.dir / "story.mp4"
        endcard = self.dir / "endcard.mp4"
        _make_clip(story, seconds=4.0, color="red")
        _make_clip(endcard, seconds=3.0, color="blue")
        self.content = self.dir / "content.mp4"
        concat_list = self.dir / "concat.txt"
        concat_list.write_text(f"file '{story}'\nfile '{endcard}'\n", encoding="utf-8")
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", str(concat_list), "-c", "copy", str(self.content)],
                       check=True, capture_output=True)

        self.ad = self.dir / "ad.mp4"
        _make_clip(self.ad, seconds=5.0, color="green")
        self.ad_sha = _sha256(self.ad)
        self.ad_qa = self.dir / "ad.qa.json"
        self.ad_qa.write_text(json.dumps({
            "ad_tail_format": {"status": "PASS", "failures": []},
            "ad_tail_duration": {"status": "PASS", "failures": []},
            "ad_tail_loudness": {"status": "PASS", "failures": []},
            "ad_tail_label_present": {"status": "PASS", "failures": []},
            "ad_tail_ocr_clean": {"status": "PASS", "failures": []},
            "packaged_sha256": self.ad_sha,
        }), encoding="utf-8")
        self.slot_contract = self.dir / "slot.json"
        self.slot_contract.write_text(json.dumps({"ledger_dir": str(self.dir / "transactions")}),
                                      encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, **overrides):
        out = overrides.get("out", self.dir / "out.mp4")
        out_qa = overrides.get("out_qa", self.dir / "out.qa.json")
        argv = [sys.executable, str(ROOT / "tools/ad_tail_insert.py"), "insert",
                "--content", str(self.content), "--endcard-seconds", "3.0",
                "--packaged-ad", str(overrides.get("packaged_ad", self.ad)),
                "--packaged-ad-qa", str(overrides.get("packaged_ad_qa", self.ad_qa)),
                "--expected-packaged-sha256", overrides.get("expected_sha", self.ad_sha),
                "--sku", "demo_sku", "--provenance", "INBOX", "--episode", "E08",
                "--slot-contract", str(self.slot_contract), "--out", str(out), "--out-qa", str(out_qa)]
        result = subprocess.run(argv, capture_output=True, text=True)
        return result, out, out_qa

    def test_splice_lands_content_ad_endcard_in_order(self) -> None:
        result, out, out_qa = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(out_qa.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "PASS")
        total = _duration(out)
        # story(4) + ad(5) + endcard(3) = 12, allow ffmpeg re-encode rounding
        self.assertAlmostEqual(total, 12.0, delta=0.3)
        ledger = json.loads((self.dir / "transactions" / "insert_ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ledger["entries"]), 1)
        self.assertEqual(ledger["entries"][0]["status"], "PASS")

    def test_sha_mismatch_fails_closed_and_writes_nothing(self) -> None:
        result, out, out_qa = self._run(expected_sha="0" * 64)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(out.exists())
        payload = json.loads(out_qa.read_text(encoding="utf-8")) if out_qa.exists() else \
            json.loads(result.stdout)
        # either a qa file or stdout carries the failure; the splice must never run
        self.assertFalse(out.exists())

    def test_failed_packaging_diagnostic_blocks_insertion(self) -> None:
        bad_qa = self.dir / "bad.qa.json"
        bad_qa.write_text(json.dumps({
            "ad_tail_format": {"status": "PASS", "failures": []},
            "ad_tail_duration": {"status": "FAIL", "failures": ["OUT_OF_RANGE"]},
            "ad_tail_loudness": {"status": "PASS", "failures": []},
            "ad_tail_label_present": {"status": "PASS", "failures": []},
            "ad_tail_ocr_clean": {"status": "PASS", "failures": []},
            "packaged_sha256": self.ad_sha,
        }), encoding="utf-8")
        result, out, out_qa = self._run(packaged_ad_qa=bad_qa)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(out.exists())

    def test_never_overwrites_existing_output(self) -> None:
        result1, out, out_qa = self._run()
        self.assertEqual(0, result1.returncode, result1.stderr)
        result2, _, _ = self._run()
        self.assertNotEqual(0, result2.returncode)


if __name__ == "__main__":
    unittest.main()
