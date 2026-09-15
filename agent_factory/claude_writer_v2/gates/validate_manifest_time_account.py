#!/usr/bin/env python3
"""【DEPRECATED 2026-08-07 / R196 · 勿接门】Claude Writer 线 manifest 时长账校验器(v1 期,CL2X-551 三(b)/CL2X-558①)。

★弃用理由(实测,非推断):本工具的秒标解析口径停留在 v1 剧本版式。在批7-批9 的 v2 版式上,
  `NUM = r"(\\d+(?:\\.\\d+)?)\\s*s"` 会把**逐句审计表「秒(上沿)」列**(如 2.2s / 0.9s)当成逐镜秒标收进来,
  于是 A3(逐场秒标和)与 A4(逐镜 >=4s)双双出假 BLOCKER。
  对照组实测(2026-08-07):**E59 / E61 / E62 三集均被本工具判 BLOCKER(28-33 条),而这三集监制均已独立复算判 PASS**
  → 是尺子坏了,不是稿子坏了(同 CL2X-1033「新写的门第一次出 FAIL,先怀疑门再怀疑稿」)。

★现行单一实现 = `tools/batch_script_verifier.py`(M-089 规则①/③)。时长三口径、逐镜 4-15s、
  逐镜物理门、相对日词、首帧动势唯一性一律以它为准。**本文件保留仅为历史记录,禁接入任何门**;
  若日后要复活,须先把秒标解析限定到镜头标题行的括注,并在 E59/E61/E62 三集上先复现监制已公开的 PASS 值(先在已知量上校尺)。

断言(任一违反=blocker,退出码 1):
  A1. sum(scene_breakdown_seconds) == total_seconds
  A2. runtime_min <= total_seconds <= runtime_max
  A3. 剧本正文逐镜秒标(实拍口径)逐场求和 == manifest scene_breakdown_seconds
  A4. 任一逐镜秒标 >= 4s(Seedance 4-15s 硬门下限;>15s 者告警,须以"连续动作单元"呈现)
  A5. manifest 全文禁句检测:"按剪辑压至"/"压缩剪法"/"叠化压缩"/"按叠化压缩"
      (CL2X-551 三(a):账必须在剧本层平,不得指望剪辑收拾)

秒标口径(与本工具同源,单一实现):
  剧本行中(排除〔palette 行与 > [依据 行)的括号组内 "Ns" 记号;
  组内取首个未被 ≤ ≥ < > ~ 均 前缀修饰的数字。场 = **NN-M．** 标题分段。

用法: python3 validate_manifest_time_account.py [E54 E55 ... | 缺省=scripts 目录全部 E*_manifest.json]
"""
import json
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GRP = re.compile(r"[（(]([^（()）]*)[)）]")
NUM = re.compile(r"(\d+(?:\.\d+)?)\s*s(?![a-zA-Z])")
SCENE = re.compile(r"\*\*(\d+-\d+)[．.]")
BANNED = ["按剪辑压至", "压缩剪法", "叠化压缩", "按叠化压缩"]


def script_scene_marks(md_text):
    scenes, cur = {}, None
    for line in md_text.split("\n"):
        m = SCENE.match(line)
        if m:
            cur = m.group(1)
            scenes[cur] = []
            continue
        if cur is None or line.startswith("〔") or line.startswith("> ["):
            continue
        for g in GRP.finditer(line):
            t = g.group(1)
            for n in NUM.finditer(t):
                pre = t[: n.start()]
                if pre and pre[-1] in "≤≥<>~均":
                    continue
                scenes[cur].append(float(n.group(1)))
                break
    return scenes


def validate(manifest_path):
    errors, warnings = [], []
    d = json.loads(Path(manifest_path).read_text())
    raw = Path(manifest_path).read_text()
    for phrase in BANNED:
        if phrase in raw:
            errors.append(f"A5 禁句: '{phrase}' 出现在 manifest")
    bd = d.get("scene_breakdown_seconds") or {}
    tot = d.get("total_seconds")
    rng = d.get("runtime_range_seconds") or {}
    s = sum(bd.values())
    if tot is None or s != tot:
        errors.append(f"A1 自账不平: sum(breakdown)={s} != total={tot}")
    if rng and not (rng.get("min", 0) <= (tot or 0) <= rng.get("max", 10**9)):
        errors.append(f"A2 越界: total={tot} 不在 [{rng.get('min')},{rng.get('max')}]")
    sf = d.get("script_file")
    md_path = SCRIPTS_DIR / Path(sf).name if sf else None
    if md_path is None or not md_path.exists():
        cands = list(SCRIPTS_DIR.glob(f"E{d.get('episode', '??')}剧本_ClaudeWriter_v*.md"))
        md_path = cands[0] if cands else None
    if md_path and md_path.exists():
        sc = script_scene_marks(md_path.read_text())
        for k, v in bd.items():
            sv = sum(sc.get(k, []))
            if abs(sv - v) > 0.51:
                errors.append(f"A3 剧本层不符: {k} manifest={v} 剧本秒标和={sv:.0f}")
        for k, v in sc.items():
            for shot in v:
                if shot < 4:
                    errors.append(f"A4 逐镜<4s: {k} 有 {shot}s 镜(Seedance 下限)")
                elif shot > 15:
                    warnings.append(f"A4w 逐镜>15s: {k} 有 {shot:.0f}s 标——须为连续动作单元(8-15s 实体参考驱动)或再切分")
    else:
        warnings.append("A3 跳过: 找不到剧本文件")
    return errors, warnings


def main():
    args = sys.argv[1:]
    print("!! DEPRECATED (R196 2026-08-07): 本工具秒标解析停留在 v1 版式,在 v2 剧本上会把审计表"
          "「秒(上沿)」列误收为逐镜秒标,对 E59/E61/E62(监制已 PASS)全部出假 BLOCKER。"
          "现行单一实现 = tools/batch_script_verifier.py。以下输出仅供历史比对,禁作门判依据。",
          file=sys.stderr)
    if "--force" not in args:
        print("已停用:如确需运行,请加 --force(结果不得用于门判)。", file=sys.stderr)
        sys.exit(2)
    args = [a for a in args if a != "--force"]
    if args:
        targets = [SCRIPTS_DIR / f"{a.upper()}_manifest.json" for a in args]
    else:
        targets = sorted(SCRIPTS_DIR.glob("E*_manifest.json"))
    failed = 0
    for t in targets:
        errs, warns = validate(t)
        status = "PASS" if not errs else "BLOCKER"
        print(f"{t.name}: {status}")
        for e in errs:
            print(f"  ERROR {e}")
        for w in warns:
            print(f"  WARN  {w}")
        failed += bool(errs)
    print(f"\n{len(targets)-failed}/{len(targets)} PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
