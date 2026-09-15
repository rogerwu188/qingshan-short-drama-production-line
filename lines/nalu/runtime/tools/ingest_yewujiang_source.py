"""Split the decoded novel into clean per-chapter source files for the nalu line (v2).

Rules:
- headings are grouped by chapter number; when a number appears more than once,
  the longest body wins (site dumps repeat headings and emit stubs);
- strip the e-book-site advertisement lines and the '『...』' header block;
- write traditional (as delivered) and simplified (OpenCC t2s) copies;
- report missing chapter numbers; never touch the original file in ~/Documents.
"""
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import hashlib, json, pathlib, re, shutil
from opencc import OpenCC

SRC = pathlib.Path("/tmp/yewujiang_utf8.txt")
ORIGIN = pathlib.Path(os.environ["NALU_SOURCE_TXT"]) if os.environ.get("NALU_SOURCE_TXT") else None  # the licensed source text is supplied by the line owner, never shipped
OUT = pathlib.Path(f"{_np.RUNTIME_ROOT}/sources/夜无疆")
cc = OpenCC("t2s")
KEEP_ZHU = ("著作", "著名", "显著", "土著", "编著", "著述", "著称", "专著", "昭著", "卓著", "原著", "著录", "著书")
def normalize_simplified(t: str) -> str:
    # OpenCC keeps 著 (valid in 著作); the site text uses it as the aspect particle 着.
    out = []
    i = 0
    while i < len(t):
        if t[i] == "著" and not any(t[max(0, i-1):i+2].find(w) >= 0 or t[i:i+2] == w or t[i-1:i+1] == w for w in KEEP_ZHU):
            out.append("着")
        else:
            out.append(t[i])
        i += 1
    t = "".join(out)
    return t.replace("「", "“").replace("」", "”").replace("『", "‘").replace("』", "’")

text = SRC.read_text(encoding="utf-8")
lines = text.split("\n")
pat = re.compile(r"^\s*第\s*(\d+)\s*章\s*(.*)$")
AD = re.compile(r"ixdzs|愛下電子書|更多電子書|E-mail", re.I)

heads = []
for i, l in enumerate(lines):
    m = pat.match(l.strip())
    if m:
        heads.append((i, int(m.group(1)), m.group(2).strip()))

segments = []  # (num, title, body_lines)
for k, (i, num, title) in enumerate(heads):
    end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
    body = []
    for l in lines[i + 1:end]:
        s = l.replace("　", "").strip()
        if not s or AD.search(s) or s in {">", "『還在連載中...』"}:
            continue
        body.append(s)
    segments.append((num, title, body))

by_num = {}
dup_report = []
for num, title, body in segments:
    cur = by_num.get(num)
    if cur is None or len("".join(body)) > len("".join(cur[1])):
        if cur is not None:
            dup_report.append({"chapter": num, "kept_chars": len("".join(body)), "dropped_chars": len("".join(cur[1]))})
        by_num[num] = (title, body)
    else:
        dup_report.append({"chapter": num, "kept_chars": len("".join(cur[1])), "dropped_chars": len("".join(body))})

nums = sorted(by_num)
missing = [n for n in range(1, nums[-1] + 1) if n not in by_num]
short = [n for n in nums if len("".join(by_num[n][1])) < 500]

for d in ("zh-Hant", "zh-CN"):
    shutil.rmtree(OUT / d, ignore_errors=True)
    (OUT / d).mkdir(parents=True, exist_ok=True)
index = []
for n in nums:
    title, body = by_num[n]
    name = f"ch{n:04d}.md"
    trad = f"# 第{n}章 {title}\n\n" + "\n\n".join(body) + "\n"
    simp = normalize_simplified(cc.convert(trad))
    (OUT / "zh-Hant" / name).write_text(trad, encoding="utf-8")
    (OUT / "zh-CN" / name).write_text(simp, encoding="utf-8")
    index.append({
        "chapter": n,
        "title_zh_cn": cc.convert(title),
        "file_zh_cn": f"zh-CN/{name}",
        "file_zh_hant": f"zh-Hant/{name}",
        "chars": len("".join(body)),
        "sha256_zh_cn": hashlib.sha256(simp.encode("utf-8")).hexdigest(),
    })

meta = {
    "schema": "nalu.source_index.v1",
    "work": "夜无疆",
    "author": "辰东",
    "origin_file": str(ORIGIN),
    "origin_sha256": hashlib.sha256(ORIGIN.read_bytes()).hexdigest(),
    "origin_encoding": "gb18030",
    "origin_script": "zh-Hant (machine-converted from the simplified original)",
    "canonical_reading_script": "zh-CN (OpenCC t2s of the delivered text)",
    "origin_quality_note": "Third-party e-book dump: duplicated headings, stub chapters and missing chapters were present; see duplicates_resolved / missing_chapters. Replace with the official text when available.",
    "authorization": "PENDING_OFFLINE_BY_OWNER (Roger, 2026-09-09): adaptation rights to be settled offline; not verified by the engine",
    "chapter_count": len(nums),
    "highest_chapter": nums[-1],
    "missing_chapters": missing,
    "duplicates_resolved": dup_report,
    "short_chapters_under_500_chars": short,
    "chapters": index,
}
(OUT / "SOURCE_INDEX.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: v for k, v in meta.items() if k != "chapters"}, ensure_ascii=False, indent=2))
