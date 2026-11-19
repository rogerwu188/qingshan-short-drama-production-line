#!/usr/bin/env python3
"""intake_source_text.py — put a delivered novel/script text file into the runtime's canonical source layout.

Generalised from the one-off ingest script a production line used for its first work (2026-09-09).  It does
exactly what that line did by hand, nothing more:

* detect the encoding (UTF-8 / UTF-8-BOM / Shift_JIS / EUC-JP / CP949 / GB18030 / GBK), decode once, never touch
  the original file; GB18030 decodes almost any byte string, so a Japanese or Korean legacy encoding is tried
  first and kept only when the text reads as that language (kana / spaced Hangul; 2026-11-18);
  a delivered .docx / .epub / .html / .htm / .md file is read as text first (standard library only; owner
  2026-11-05: the line owner may send the source file through the StoryClaw agent);
* a text-layer .pdf is read with ``pdftotext`` (poppler) when it is installed;
* split by chapter heading (default regex ``^第[0-9一二三四五六七八九十百千零〇两]+章``; Japanese ``第N話`` /
  ``第N章``, Korean ``제N장`` / ``N화`` with ``--language ja|ko`` or a detected language); when the same
  chapter number appears more than once (e-book dumps repeat headings and emit stubs) the LONGEST body wins;
* drop advertisement / site-header lines matching ``--drop-regex``;
* write the text as delivered (``as_delivered/``) and, when ``--to-simplified`` is given for a Chinese source
  (never Japanese / Korean: t2s would rewrite kanji) and OpenCC is
  installed, a simplified copy (``zh-CN/``); the aspect particle 著→着 is normalised outside a fixed list of
  著-words (著作/原著/显著…) because site dumps use 著 for 着;
* write ``SOURCE_INDEX.json`` with the origin path, sha256, encoding, chapter count, missing chapter numbers
  and the authorisation note the deployer states (the engine never verifies rights).

No network, no provider, no credentials.  Status: REFERENCE_IMPLEMENTATION (the production line ran a
work-specific variant of this logic; this generalised CLI has unit-level coverage only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CN_NUM = "0-9一二三四五六七八九十百千零〇两"
DEFAULT_HEADING = rf"^\s*第([{CN_NUM}]+)章[^\n]*$"
#: Japanese 第N話 / 第N章 (full-width digits too), Korean 제N장 / 제N화 / N화 (2026-11-18)
DEFAULT_HEADING_BY_LANGUAGE = {
    "ja": rf"^\s*第([{CN_NUM}０-９]+)[話章][^\n]*$",
    "ko": r"^\s*(?:제\s*)?([0-9]+)\s*(?:장|화)(?:[\s.:：\-—].*)?$",
}
DEFAULT_DROP = r"(https?://|www\.|本书由|更多精彩|请记住本站|『.*』|最新章节)"
KEEP_ZHU = ("著作", "著名", "显著", "土著", "编著", "著述", "著称", "专著", "昭著", "卓著", "原著", "著录", "著书")
CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
_HANGUL = re.compile(r"[\uac00-\ud7a3]")


def _reads_as(text: str, language: str) -> bool:
    """A strict decode that also reads as the language: Japanese has kana (>= 5 % of the non-space
    characters); Korean is mostly Hangul AND puts spaces between words (GB2312 Chinese decoded as EUC-KR
    becomes Hangul too, but without the spaces)."""
    body = re.sub(r"\s", "", text)
    if not body:
        return False
    if language == "ja":
        return len(_KANA.findall(body)) / len(body) >= 0.05
    hangul = len(_HANGUL.findall(body))
    return hangul / len(body) >= 0.3 and text.count(" ") / max(1, hangul) >= 0.12


def decode(raw: bytes, language: str | None = None) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # legacy Japanese / Korean encodings first: gb18030 maps almost every byte pair and would silently
    # garble them (a hint narrows the order, the reading test still has to pass)
    legacy = (("cp932", "ja"), ("euc_jp", "ja"), ("cp949", "ko"))
    if language in ("ja", "ko"):
        legacy = tuple(row for row in legacy if row[1] == language) + tuple(r for r in legacy if r[1] != language)
    for enc, lang in legacy:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if _reads_as(text, lang):
            return text, enc
    for enc in ("gb18030", "gbk"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit("cannot decode input as UTF-8 / Shift_JIS / EUC-JP / CP949 / GB18030 / GBK; convert it first")


def detect_language(text: str) -> str:
    """ja when kana carry the text, ko when Hangul does, else zh (the historical default)."""
    sample = re.sub(r"\s", "", text[:20000])
    if not sample:
        return "zh"
    if len(_KANA.findall(sample)) / len(sample) >= 0.05:
        return "ja"
    if len(_HANGUL.findall(sample)) / len(sample) >= 0.3:
        return "ko"
    return "zh"


def _xml_text(xml: str, block_tags: str) -> str:
    """Plain text of an XML/HTML document: a newline after every block element, entities unescaped."""
    import html as _html
    xml = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", xml)
    xml = re.sub(rf"(?i)</({block_tags})>|<br\s*/?>", "\n", xml)
    text = _html.unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"\n[ \t]*\n+", "\n", text)


def read_delivered(src: Path, language: str | None = None) -> tuple[str, str]:
    """(text, how) for a delivered .txt/.md, .docx, .epub or .html file."""
    import zipfile
    suffix = src.suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(src) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        return _xml_text(xml.replace("<w:tab/>", "\t"), "w:p"), "docx"
    if suffix == ".epub":
        with zipfile.ZipFile(src) as z:
            opf_path = re.search(r'full-path="([^"]+)"', z.read("META-INF/container.xml").decode("utf-8")).group(1)
            opf = z.read(opf_path).decode("utf-8")
            base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
            items = dict(re.findall(r'<item[^>]*?id="([^"]+)"[^>]*?href="([^"]+)"', opf))
            items.update({i: h for h, i in re.findall(r'<item[^>]*?href="([^"]+)"[^>]*?id="([^"]+)"', opf)})
            order = re.findall(r'<itemref[^>]*?idref="([^"]+)"', opf)
            parts = [_xml_text(z.read(base + items[i]).decode("utf-8", "ignore"), "p|div|h[1-6]|li")
                     for i in order if i in items]
        return "\n".join(parts), "epub"
    if suffix in (".html", ".htm"):
        text, enc = decode(src.read_bytes(), language)
        return _xml_text(text, "p|div|h[1-6]|li"), f"html:{enc}"
    if suffix == ".pdf":
        import shutil
        import subprocess
        tool = shutil.which("pdftotext")
        if not tool:
            raise SystemExit("PDF needs pdftotext (poppler-utils): install it, or convert to .txt first, then intake the .txt")
        done = subprocess.run([tool, "-enc", "UTF-8", str(src), "-"], capture_output=True, check=False)
        text = done.stdout.decode("utf-8", "replace").replace("\f", "\n")
        if done.returncode != 0 or not text.strip():
            raise SystemExit(f"pdftotext found no text layer in {src.name} (scanned PDF?): OCR it first")
        return text, "pdf:pdftotext"
    return decode(src.read_bytes(), language)


def cn_to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    total, section, number = 0, 0, 0
    for ch in token:
        if ch in CN_DIGITS:
            number = CN_DIGITS[ch]
        elif ch == "十":
            section += (number or 1) * 10; number = 0
        elif ch == "百":
            section += (number or 1) * 100; number = 0
        elif ch == "千":
            section += (number or 1) * 1000; number = 0
        else:
            return None
    return total + section + number


def normalize_simplified(text: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch == "著":
            window = text[max(0, i - 1):i + 2]
            if any(word in window or text[i:i + 2] == word or text[max(0, i - 1):i + 1] == word for word in KEEP_ZHU):
                out.append(ch)
            else:
                out.append("着")
        else:
            out.append(ch)
    return "".join(out)


def split_chapters(text: str, heading_re: re.Pattern[str], drop_re: re.Pattern[str] | None) -> dict[int, tuple[str, str]]:
    lines = text.splitlines()
    chapters: dict[int, tuple[str, str]] = {}
    current: int | None = None
    title = ""
    body: list[str] = []

    def flush() -> None:
        if current is None:
            return
        candidate = "\n".join(body).strip()
        prior = chapters.get(current)
        if prior is None or len(candidate) > len(prior[1]):
            chapters[current] = (title, candidate)

    for line in lines:
        if drop_re and drop_re.search(line):
            continue
        match = heading_re.match(line)
        if match:
            number = cn_to_int(match.group(1))
            if number is not None:
                flush()
                current, title, body = number, line.strip(), []
                continue
        if current is not None:
            body.append(line.rstrip())
    flush()
    return chapters


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--input", required=True, help="delivered .txt/.md/.docx/.epub/.html file (never modified)")
    ap.add_argument("--work", required=True, help="work title, used as the source folder name")
    ap.add_argument("--out", required=True, help="runtime sources root, e.g. $RUNTIME_ROOT/sources")
    ap.add_argument("--author", default="")
    ap.add_argument("--authorization", default="", help="deployer's rights statement, recorded verbatim")
    ap.add_argument("--heading-regex", default=None,
                    help="chapter heading regex (group 1 = the number); default by language: 第N章 (zh), "
                         "第N話 / 第N章 (ja), 제N장 / N화 (ko)")
    ap.add_argument("--language", choices=("zh", "en", "ja", "ko"),
                    help="source language (default: detected from the text; decides the heading default, the "
                         "legacy encoding tried first, and that --to-simplified never applies to ja / ko)")
    ap.add_argument("--drop-regex", default=DEFAULT_DROP)
    ap.add_argument("--to-simplified", action="store_true", help="also write a zh-CN copy (needs opencc)")
    ap.add_argument("--dry-run", action="store_true", help="report chapter split only, write nothing")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    if not src.is_file():
        raise SystemExit(f"input not found: {src}")
    raw = src.read_bytes()
    text, encoding = read_delivered(src, args.language)
    language = args.language or detect_language(text)
    heading_re = re.compile(args.heading_regex or DEFAULT_HEADING_BY_LANGUAGE.get(language, DEFAULT_HEADING), re.M)
    drop_re = re.compile(args.drop_regex) if args.drop_regex else None
    chapters = split_chapters(text, heading_re, drop_re)
    if not chapters:
        raise SystemExit("no chapter headings matched; pass --heading-regex")
    numbers = sorted(chapters)
    missing = [n for n in range(numbers[0], numbers[-1] + 1) if n not in chapters]

    cc = None
    if args.to_simplified and language in ("ja", "ko"):
        print(json.dumps({"status": "TO_SIMPLIFIED_SKIPPED", "language": language,
                          "detail": "traditional -> simplified never applies to a Japanese / Korean source"}),
              file=sys.stderr)
    elif args.to_simplified:
        try:
            from opencc import OpenCC  # type: ignore
            cc = OpenCC("t2s")
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"status": "ADAPTER_REQUIRED", "detail": f"opencc unavailable: {exc}"}))
            return 2

    out_root = Path(args.out).resolve() / args.work
    report = {
        "schema": "qingshan.source_intake.v1",
        "status": "DRY_RUN" if args.dry_run else "WRITTEN",
        "work": args.work,
        "author": args.author,
        "origin_file": str(src),
        "origin_sha256": hashlib.sha256(raw).hexdigest(),
        "origin_encoding": encoding,
        **({"source_language": language} if language != "zh" else {}),
        "chapters_found": len(chapters),
        "chapter_range": [numbers[0], numbers[-1]],
        "missing_chapter_numbers": missing,
        "simplified_copy": bool(cc),
        "authorization": args.authorization,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": "the engine records the deployer's rights statement; it does not verify adaptation rights",
    }
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    (out_root / "as_delivered").mkdir(parents=True, exist_ok=True)
    if cc:
        (out_root / "zh-CN").mkdir(parents=True, exist_ok=True)
    for number in numbers:
        title, body = chapters[number]
        page = f"# {title}\n\n{body}\n"
        (out_root / "as_delivered" / f"ch{number:04d}.md").write_text(page, encoding="utf-8")
        if cc:
            (out_root / "zh-CN" / f"ch{number:04d}.md").write_text(normalize_simplified(cc.convert(page)), encoding="utf-8")
    report["canonical_reading_script"] = "zh-CN" if cc else "as_delivered"
    (out_root / "SOURCE_INDEX.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "chapters_found", "chapter_range", "missing_chapter_numbers", "origin_encoding")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
