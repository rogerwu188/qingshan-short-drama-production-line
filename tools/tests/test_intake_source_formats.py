"""intake_source_text reads a delivered .txt (GBK), .docx and .epub the same way (owner 2026-11-05)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "intake_source_text.py"
BODY = ["第一章 卷了四百年", "沈棠在蒲团上坐了四百年。", "第二章 魔尊打上门", "沈棠翻了个身。"]


def _run(src: Path, out: Path) -> dict:
    done = subprocess.run([sys.executable, str(TOOL), "--input", str(src), "--work", "测试", "--out", str(out)],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout.strip().splitlines()[-1])


class IntakeFormatsTest(unittest.TestCase):
    def check(self, src: Path, tmp: Path):
        res = _run(src, tmp / "out")
        self.assertEqual(res["chapters_found"], 2)
        ch2 = next((tmp / "out").rglob("ch0002.md")).read_text(encoding="utf-8")
        self.assertIn("沈棠翻了个身", ch2)

    def test_gbk_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "novel.txt"
            src.write_bytes("\n".join(BODY).encode("gbk"))
            self.check(src, Path(tmp))

    def test_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "novel.docx"
            paras = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in BODY)
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{paras}</w:body></w:document>')
            self.check(src, Path(tmp))

    def test_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "novel.epub"
            with zipfile.ZipFile(src, "w") as z:
                z.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
                z.writestr("OEBPS/c.opf", '<package><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/>'
                                          '</manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>')
                z.writestr("OEBPS/a.xhtml", f"<html><body><h1>{BODY[0]}</h1><p>{BODY[1]}</p></body></html>")
                z.writestr("OEBPS/b.xhtml", f"<html><body><h1>{BODY[2]}</h1><p>{BODY[3]}</p></body></html>")
            self.check(src, Path(tmp))


if __name__ == "__main__":
    unittest.main()
