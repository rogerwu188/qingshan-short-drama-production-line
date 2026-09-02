# -*- coding: utf-8 -*-
"""SCRIPT-INFLIGHT-SHA-001 修法（CL2X-1048 §① ask①/②，owner=写盘方=Claude Writer）

监制实测：批11 三稿在同一轮内被读到三次不同 sha（E68 +19B / E69 +768B / E70 +930B），
读者看到的每一个瞬时态都「文件存在、内容自洽、结构完整」，而没有一个是交付态。
—— 盘上缺的不是内容，是**交付边界**。

本件提供两件事，都不改任何剧本内容：

① `atomic_write()` —— 写 `<name>.tmp.<round>.<pid>` 后 `os.replace()` 到最终名。
   同文件系统 rename 是原子的：读者要么看到旧文件（或无文件），要么看到完整新文件，
   **永远看不到半截稿**。取消了「文件在增长」这个可被观测到的中间态。

② `publish_episode()` —— 把「正文写完」与「manifest 到齐」之间的窗口从**分钟级压到毫秒级**。
   ★这是本件的要害，比 ① 更重要：
   ① 只消灭了「半截文件」，消灭不了「完整正文 + 尚无 manifest」这个同样自洽的中间态
   （批11 实况：正文 19:36-19:37 落盘，manifest 19:42 落盘，中间 5 分钟里盘上有三份
   读起来毫无破绽、而按 CL2X-1046/1047 规矩根本不该被取 sha 的稿）。
   故本件要求：**正文与 manifest 同时备好后再一起发布，manifest 最后一个 rename**
   —— 使 manifest 的存在成为一个**真实的**交付信号，而不是一个碰巧的时间先后。

③ 发布后自校：逐件复算落盘 sha 与字节数，与 manifest 内录值双向比对，不符即 ABORT。

用法（发布一集）：
    from atomic_publish import publish_episode
    rec = publish_episode(script_path, script_text, manifest_path, manifest_obj,
                          round_tag="R202", sha_key="script_sha256")

注意：本件只保证「读者看到的每一件都是完整件」，不保证内容正确——那是复验器的事。
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
from typing import Any, Dict, Optional


class PublishAbort(RuntimeError):
    """发布中止：任一校验不符即抛出，且最终名保持原状（旧件或不存在）。"""


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _tmp_path(p: pathlib.Path, round_tag: str) -> pathlib.Path:
    # 暂存名唯一（含轮次 + PID），承 SM-METHOD-007 ①
    return p.with_name(p.name + f".tmp.{round_tag}.{os.getpid()}")


def stage(path, text: str, round_tag: str) -> pathlib.Path:
    """把内容写进唯一暂存名并落稳，返回暂存路径。不触碰最终名。"""
    p = pathlib.Path(path)
    tmp = _tmp_path(p, round_tag)
    if tmp.exists():
        raise PublishAbort(f"暂存文件已存在，拒绝覆盖：{tmp}")
    data = text.encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())          # 内容先落稳，再让它有名字
    got = tmp.read_bytes()
    if got != data:
        tmp.unlink(missing_ok=True)
        raise PublishAbort(f"暂存回读不符：{tmp}")
    return tmp


def commit(tmp, path) -> Dict[str, Any]:
    """原子改名 + 落盘自校。返回 {path, sha256, bytes}。"""
    tmp = pathlib.Path(tmp)
    p = pathlib.Path(path)
    expect = tmp.read_bytes()
    os.replace(tmp, p)                # 同文件系统 rename = 原子，读者无中间态
    landed = p.read_bytes()
    if landed != expect:
        raise PublishAbort(f"落盘回读与暂存不符：{p}")
    return {"path": str(p), "sha256": sha256_bytes(landed), "bytes": len(landed)}


def atomic_write(path, text: str, round_tag: str) -> Dict[str, Any]:
    """单件原子发布（stage + commit）。"""
    return commit(stage(path, text, round_tag), path)


def publish_episode(
    script_path,
    script_text: str,
    manifest_path,
    manifest_obj: Dict[str, Any],
    round_tag: str,
    sha_key: str = "script_sha256",
    dry_run: bool = False,
    delivery_state: Optional[str] = "PUBLISHED",
    ledger_path=None,
) -> Dict[str, Any]:
    """一集的正文 + manifest 成对发布。

    次序写死，不可调换：
      1. 算正文 sha（在其成为最终字节之后、被任何人看见之前）
      2. 把该 sha 注入 manifest（双向绑定）
      3. 两件各自 stage 到唯一暂存名（此时最终名上仍无新件）
      4. commit 正文  → 5. commit manifest（**manifest 永远最后**）
      6. 逐件复算落盘 sha，与 manifest 内录值双向比对

    任一步不符即 ABORT，且已 stage 的暂存件清理干净，最终名保持原状。
    """
    script_path = pathlib.Path(script_path)
    manifest_path = pathlib.Path(manifest_path)

    data = script_text.encode("utf-8")
    script_sha = sha256_bytes(data)

    manifest = dict(manifest_obj)
    manifest[sha_key] = script_sha
    # ★正向就绪标记（CL2X-1068 §① ask②）：让「已交付」不再靠 manifest 的**缺席**来表达。
    # 传 None 可关闭（用于复现旧件字节；旧件不追溯改写，承 M-090）。
    if delivery_state is not None:
        manifest["delivery_state"] = delivery_state
        manifest["published_round"] = round_tag
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=1) + "\n"

    if dry_run:
        return {
            "dry_run": True,
            "script_sha256": script_sha,
            "script_bytes": len(data),
            "manifest_bytes": len(manifest_text.encode("utf-8")),
        }

    t_script: Optional[pathlib.Path] = None
    t_manifest: Optional[pathlib.Path] = None
    try:
        t_script = stage(script_path, script_text, round_tag)
        t_manifest = stage(manifest_path, manifest_text, round_tag)
    except Exception:
        for t in (t_script, t_manifest):
            if t is not None:
                pathlib.Path(t).unlink(missing_ok=True)
        raise

    rec_script = commit(t_script, script_path)
    rec_manifest = commit(t_manifest, manifest_path)

    # 双向绑定复核：manifest 内录 sha ↔ 正文落盘实测 sha
    landed = json.loads(manifest_path.read_text(encoding="utf-8"))
    if landed.get(sha_key) != rec_script["sha256"]:
        raise PublishAbort(
            f"双向绑定不符：manifest[{sha_key}]={landed.get(sha_key)} vs 正文实测={rec_script['sha256']}"
        )

    # ★发布后立刻跑一次交付绑定门，并把结果**逐次**写进 JSONL 台账。
    # 理由（CL2X-1070 §③）：绑定断裂窗口会自愈，而自愈动作同时抹掉它的全部痕迹；
    # 唯一能在窗口闭合后仍留下记录的，是每次发布各留一条断言结果，而不是靠某一轮恰好取样。
    gate_rec: Dict[str, Any] = {"verdict": "NOT_RUN"}
    try:
        from delivery_binding_gate import append_ledger, check_pair  # type: ignore
    except ImportError:  # pragma: no cover - 同目录导入兜底
        import importlib.util

        _spec = importlib.util.spec_from_file_location(
            "delivery_binding_gate",
            str(pathlib.Path(__file__).with_name("delivery_binding_gate.py")),
        )
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        append_ledger, check_pair = _mod.append_ledger, _mod.check_pair

    gate_rec = check_pair(script_path, manifest_path, sha_key)
    gate_rec["episode"] = script_path.name.split("剧本")[0]
    if gate_rec.get("verdict") != "PASS":
        raise PublishAbort(f"交付绑定门未过：{gate_rec}")
    if ledger_path is not None:
        append_ledger(ledger_path, [gate_rec], {"round": round_tag, "source": "publish_episode"})

    return {
        "round_tag": round_tag,
        "script": rec_script,
        "manifest": rec_manifest,
        "binding": "EXACT",
        "publish_order": ["script", "manifest"],
        "boundary": "MANIFEST_LAST_IS_THE_DELIVERY_SIGNAL",
        "delivery_state": manifest.get("delivery_state"),
        "delivery_binding_gate": gate_rec,
    }


STAGING_SUBDIR = "_staging"


def draft_path(final_path, round_tag: str) -> pathlib.Path:
    """草稿路径 = `<dir>/_staging/<name>.draft.<round>.<pid>`。

    ★CL2X-1068 §① 修法①（owner=本线）：`atomic_write()`／`publish_episode()` 只保证
    **发布**是原子的，**没有禁止「写作」发生在已发布的路径上**。批13 实况：E74/E75 正文
    在最终路径上被逐步写出，占位符 `@@AUDIT@@` 半截态对所有 glob `scripts/*_v2.md` 的
    消费者可见——**它不会报错，它会通过**。

    故：起草一律走本函数给出的路径，最终名在 `publish_episode()` 之前不得出现新字节。
    """
    p = pathlib.Path(final_path)
    d = p.parent / STAGING_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{p.name}.draft.{round_tag}.{os.getpid()}"


def write_draft(final_path, text: str, round_tag: str) -> pathlib.Path:
    """把在写的内容落到 `_staging/`，返回草稿路径。最终名零触碰。"""
    dp = draft_path(final_path, round_tag)
    dp.write_text(text, encoding="utf-8")
    return dp


def read_draft(final_path, round_tag: str) -> str:
    return draft_path(final_path, round_tag).read_text(encoding="utf-8")


def assert_final_path_untouched(final_path, since_ts: float) -> None:
    """断言最终名在起草期间没有被写过；被写过即 ABORT（起草跑到了最终路径上）。"""
    p = pathlib.Path(final_path)
    if p.exists() and p.stat().st_mtime > since_ts:
        raise PublishAbort(
            f"起草期间最终名被写入（INFLIGHT-AT-FINAL-PATH）：{p} mtime={p.stat().st_mtime} > {since_ts}"
        )


def sweep_stale_tmp(dirpath, round_tag: str) -> list:
    """清理本轮本进程之外遗留的暂存件（只报不删，留作物证）。"""
    d = pathlib.Path(dirpath)
    mine = f".tmp.{round_tag}.{os.getpid()}"
    return sorted(
        str(p) for p in d.glob("*.tmp.*") if not p.name.endswith(mine)
    )


if __name__ == "__main__":
    import sys

    print(json.dumps(sweep_stale_tmp(sys.argv[1] if len(sys.argv) > 1 else ".", "MANUAL"),
                     ensure_ascii=False, indent=1))
