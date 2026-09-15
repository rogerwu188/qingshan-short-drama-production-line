#!/usr/bin/env python3
"""intake_source_text.py — put a delivered novel/script text file into the runtime's canonical source layout.

Generalised from the one-off ingest script a production line used for its first work (2026-09-09).  It does
exactly what that line did by hand, nothing more:

* detect the encoding (UTF-8 / UTF-8-BOM / GB18030 / GBK), decode once, never touch the original file;
* split by chapter heading (default regex ``^第[0-9一二三四五六七八九十百千零〇两]+章``); when the same
  chapter number appears more than once (e-book dumps repeat headings and emit stubs) the LONGEST body wins;
* drop advertisement / site-header lines matching ``--drop-regex``;
* write the text as delivered (``as_delivered/``) and, when ``--to-simplified`` is given and OpenCC is
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
DEFAULT_DROP = r"(https?://|www\.|本书由|更多精彩|请记住本站|『.*』|最新章节)"
KEEP_ZHU = ("著作", "著名", "显著", "土著", "编著", "著述", "著称", "专著", "昭著", "卓著", "原著", "著录", "著书")
CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit("cannot decode input as UTF-8 / GB18030 / GBK; convert it first")


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
    ap.add_argument("--input", required=True, help="delivered text file (never modified)")
    ap.add_argument("--work", required=True, help="work title, used as the source folder name")
    ap.add_argument("--out", required=True, help="runtime sources root, e.g. $RUNTIME_ROOT/sources")
    ap.add_argument("--author", default="")
    ap.add_argument("--authorization", default="", help="deployer's rights statement, recorded verbatim")
    ap.add_argument("--heading-regex", default=DEFAULT_HEADING)
    ap.add_argument("--drop-regex", default=DEFAULT_DROP)
    ap.add_argument("--to-simplified", action="store_true", help="also write a zh-CN copy (needs opencc)")
    ap.add_argument("--dry-run", action="store_true", help="report chapter split only, write nothing")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    if not src.is_file():
        raise SystemExit(f"input not found: {src}")
    raw = src.read_bytes()
    text, encoding = decode(raw)
    heading_re = re.compile(args.heading_regex, re.M)
    drop_re = re.compile(args.drop_regex) if args.drop_regex else None
    chapters = split_chapters(text, heading_re, drop_re)
    if not chapters:
        raise SystemExit("no chapter headings matched; pass --heading-regex")
    numbers = sorted(chapters)
    missing = [n for n in range(numbers[0], numbers[-1] + 1) if n not in chapters]

    cc = None
    if args.to_simplified:
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
