#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场次来源申报门（writer 侧，生成前）。

规则：manifest.structure 里的每一个 scene_id，必须至少满足其一——
  A. 出现在 beat_disposition 的落点里（＝来自源章某一拍）；
  B. 出现在 ★authorized_insertions 的 scene_id / shots 里（＝写手自发插入且已申报）。
两者都不满足 ⇒ 该场是"无源且未申报"，FAIL。

立门缘由：E51 v4 的 S03／S08／S11 三场线B（20.8 秒，占目标片长 11.6%）
既不在 ch56 十拍的 beat_disposition 内，也未登记进 ★authorized_insertions，
混在源章内容里通过了 script phase 并已付费生成。全库回扫后确认不是孤例。

依据：SUPERVISOR_ORDERS seq=51 c2（插入项的新信息判据＝落地场次正文）
      ＋ seq=45 c5（manifest 须显式登记）
      ＋ 宪章第八节第 2 条（manifest 必填 beat_disposition）。

BILI_V1（CHANGE_SPEC WP1 第 4 条，线主 2026-11-23；``--craft-profile BILI_V1 --contract <合同>``）：
  一集按剧情事件分配（1 主 + ≤1 次），不再"一集一章、每拍落地"。合同 ``pacing.scene_plan[]``（或
  manifest ``structure[]``）里 ``source_detail_ids`` 非空的场即算"有源"；其余自创衔接场仍应申报在
  authorized_insertions，但只记 WARN、从不卡（--warn-is-fail 也不卡）。LEGACY 行为不变。
"""
import argparse, json, re, sys

SCENE_RE = re.compile(r'E\d+-S\d+')


def landed_scene_ids(bd) -> set:
    """兼容盘上两种 beat_disposition 形态：
       ① list[{event_id, disposition, landed_at, ...}]      （E51 起）
       ② dict{basis, landed:[...], merged:[...], dropped:[]} （E43–E50）
       形态②里 landed 元素可能是 dict（含 landing 字段）也可能是裸 event_id 字符串。"""
    out = set()
    if isinstance(bd, dict):
        for key in ("landed", "merged"):
            for b in bd.get(key) or []:
                out |= set(SCENE_RE.findall(json.dumps(b, ensure_ascii=False)))
    elif isinstance(bd, list):
        for b in bd:
            if isinstance(b, dict):
                out |= set(SCENE_RE.findall(str(b.get("landed_at") or b.get("landing") or "")))
    return out


def declared_scene_ids(ins) -> set:
    if not isinstance(ins, list):
        return set()
    ins = [i for i in ins if isinstance(i, dict)]
    return set(SCENE_RE.findall(json.dumps(ins, ensure_ascii=False)))


def detail_sourced_scene_ids(manifest: dict, contract: dict | None) -> set:
    """BILI_V1: scenes whose scene card declares ``source_detail_ids`` (contract pacing.scene_plan / the
    pacing_scene_plan alias, or the manifest structure row)."""
    rows = list((manifest or {}).get("structure") or [])
    contract = contract or {}
    pacing = contract.get("pacing") if isinstance(contract.get("pacing"), dict) else {}
    rows += list(pacing.get("scene_plan") or []) + list(contract.get("pacing_scene_plan") or [])
    return {str(r["scene_id"]) for r in rows
            if isinstance(r, dict) and r.get("scene_id") and [x for x in r.get("source_detail_ids") or [] if x]}


def audit(path: str, craft_profile: str = "", contract_path: str = "") -> dict:
    d = json.load(open(path, encoding="utf-8"))
    bili = str(craft_profile or "").strip().upper().replace("-", "_") == "BILI_V1"
    if bili:
        return audit_bili_v1(path, d, contract_path)
    scenes = [s["scene_id"] for s in d.get("structure", []) if isinstance(s, dict) and "scene_id" in s]
    ep = str(d.get("episode") or "")
    bd = d.get("beat_disposition")
    # 只保留本集场次号：插入项的 source_basis 常引用上游集的场次，那不是本集申报
    own = lambda S: {x for x in S if not ep or x.startswith(ep + "-")}
    landed = own(landed_scene_ids(bd))
    declared = own(declared_scene_ids(d.get("★authorized_insertions") or d.get("authorized_insertions")))

    failures, warnings = [], []

    # beat_disposition 必须能解析出场次落点，否则本门无法审计
    if scenes and not landed:
        warnings.append(
            "BEAT_DISPOSITION_HAS_NO_SCENE_LEVEL_LANDING: "
            "beat_disposition 未记录每一拍落在哪一场，本门无法审计该集；"
            "请把落点写到场次粒度（如 'E48-S03（五镜）'）后重跑。")

    undeclared = [s for s in scenes if s not in landed and s not in declared]
    if undeclared:
        failures.append("UNSOURCED_AND_UNDECLARED_SCENES:" + ",".join(undeclared))

    # 申报了但正文里没有这一场
    ghosts = [s for s in sorted(declared) if scenes and s not in scenes]
    if ghosts:
        warnings.append("DECLARED_SCENE_NOT_IN_STRUCTURE:" + ",".join(ghosts))

    return {
        "schema": "qingshan.writer_scene_source_declaration_gate.v1",
        "manifest": path,
        "episode": d.get("episode"),
        "version": d.get("version"),
        "scene_count": len(scenes),
        "scenes_from_source": sorted(s for s in scenes if s in landed),
        "scenes_declared_as_insertion": sorted(s for s in scenes if s in declared),
        "scenes_unsourced_and_undeclared": undeclared,
        "warnings": warnings,
        "failures": failures,
        "status": "FAIL" if failures else ("WARN" if warnings else "PASS"),
    }


def audit_bili_v1(path: str, d: dict, contract_path: str = "") -> dict:
    """BILI_V1: report-only.  Sourced = beat_disposition landing or source_detail_ids; never FAIL."""
    contract = {}
    cpath = contract_path or str(d.get("generation_contract") or d.get("contract") or "")
    if cpath:
        try:
            contract = json.load(open(cpath, encoding="utf-8"))
        except (OSError, ValueError):
            contract = {}
    scenes = [s["scene_id"] for s in d.get("structure", []) if isinstance(s, dict) and "scene_id" in s]
    if not scenes and isinstance(contract.get("shots"), list):
        scenes = list(dict.fromkeys(str(s.get("scene_id")) for s in contract["shots"]
                                    if isinstance(s, dict) and s.get("scene_id")))
    ep = str(d.get("episode") or contract.get("episode") or "")
    own = lambda S: {x for x in S if not ep or x.startswith(ep + "-")}
    landed = own(landed_scene_ids(d.get("beat_disposition"))) | detail_sourced_scene_ids(d, contract)
    declared = own(declared_scene_ids(d.get("★authorized_insertions") or d.get("authorized_insertions")))
    unsourced = [s for s in scenes if s not in landed and s not in declared]
    warnings = (["UNSOURCED_AND_UNDECLARED_SCENES_ADVISORY:" + ",".join(unsourced)] if unsourced else [])
    return {
        "schema": "qingshan.writer_scene_source_declaration_gate.v1",
        "manifest": path, "craft_profile": "BILI_V1", "authority": "ADVISORY_NOT_A_GATE",
        "episode": d.get("episode"), "version": d.get("version"), "scene_count": len(scenes),
        "scenes_from_source": sorted(s for s in scenes if s in landed),
        "scenes_declared_as_insertion": sorted(s for s in scenes if s in declared),
        "scenes_unsourced_and_undeclared": unsourced,
        "warnings": warnings, "failures": [], "status": "PASS",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifests", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--warn-is-fail", action="store_true",
                    help="把 WARN（beat_disposition 无场次落点）也判为失败")
    ap.add_argument("--craft-profile", default="", help="BILI_V1: source_detail_ids count as sourced; report-only")
    ap.add_argument("--contract", default="", help="BILI_V1: the generation contract (scene cards)")
    a = ap.parse_args()

    reports = [audit(p, a.craft_profile, a.contract) for p in a.manifests]
    bad = [r for r in reports if r["status"] == "FAIL" or (a.warn_is_fail and r["status"] == "WARN")]

    for r in reports:
        line = f'{r["status"]:4} {r["episode"]} {r["version"]}  场次 {r["scene_count"]}'
        if r["scenes_unsourced_and_undeclared"]:
            line += "  无源未申报: " + ",".join(r["scenes_unsourced_and_undeclared"])
        for w in r["warnings"]:
            line += "\n       WARN " + w
        print(line)

    if a.out:
        json.dump({"schema": "qingshan.writer_scene_source_declaration_gate_report.v1",
                   "reports": reports,
                   "status": "FAIL" if bad else "PASS"},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n报告已写出：{a.out}")

    print(f"\n合计 {len(reports)} 集，失败 {len(bad)} 集")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
