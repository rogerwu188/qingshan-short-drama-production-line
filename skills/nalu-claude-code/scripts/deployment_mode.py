#!/usr/bin/env python3
"""NALU deployment mode: ``fleet`` (machine-room cluster, the default) or ``single`` (one user's own machine).

Line owner 2026-11-25: single-machine users are supported.  The mode is persisted in the runtime config
``$NALU_RUNTIME_ROOT/qingshan.json`` so the system cron (``codex_production.py tick --system``, which never sees an
interactive shell's environment) follows it too:

    "deployment": {"mode": "single" | "fleet", "x2c_api_mode": "open" | "matrix"}

Precedence (each value separately):
  mode          $NALU_DEPLOYMENT_MODE  >  qingshan.json deployment.mode  >  "fleet"
  x2c_api_mode  $X2C_API_MODE          >  qingshan.json deployment.x2c_api_mode  >  "open" when mode=single
                >  "" (fleet: publish_x2c_matrix.matrix_mode() keeps its default MATRIX + legacy-series rule)

Single mode:
  * X2C goes through the legacy open-api to the user's own X2C account (category = brief ``genre`` / ``genre_lang``
    from ``publish_x2creel.py categories --lang``); no device matrix, no SN registration, no creative-context, no
    ``close``.
  * Fleet reporting stays on (NALU_FLEET_URL default unchanged); the budget default is unchanged.
  * The source novel MUST come from the user (a file under ``sources/<作品>/delivered/``); nobody scrapes the web,
    picks a public-domain book or writes an original outline: ``codex_production.py start`` returns
    BLOCKED ``SOURCE_REQUIRED_FROM_USER`` until the file is there.

  deployment_mode.py show                    print the resolved mode (and where each value came from)
  deployment_mode.py set single|fleet [--x2c-api-mode open|matrix|auto]
                                             write qingshan.json atomically (other keys untouched, file mode kept,
                                             a new file is 600); the section holds no secrets
  deployment_mode.py mode                    print just "single" or "fleet" (for shell scripts)

Never raises from the read helpers: a missing or broken qingshan.json is fleet mode.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

MODES = ("fleet", "single")
X2C_MODES = ("open", "matrix")
SOURCE_REQUIRED_REASON = "SOURCE_REQUIRED_FROM_USER"


def runtime() -> Path:
    return Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()


def config_path(root: Path | None = None) -> Path:
    return (Path(root) if root else runtime()) / "qingshan.json"


def _section(root: Path | None = None) -> dict[str, Any]:
    try:
        cfg = json.loads(config_path(root).read_text(encoding="utf-8"))
        sec = cfg.get("deployment") if isinstance(cfg, dict) else None
        return sec if isinstance(sec, dict) else {}
    except Exception:  # noqa: BLE001 -- unreadable config = fleet defaults
        return {}


def _norm_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("single", "single-machine", "single_machine", "standalone", "单机", "单机模式"):
        return "single"
    if text in ("fleet", "cluster", "matrix", "集群", "机房"):
        return "fleet"
    return ""


def _norm_x2c(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("open", "legacy", "open-api"):
        return "open"
    if text == "matrix":
        return "matrix"
    return ""


def resolve(root: Path | None = None) -> dict[str, Any]:
    """{mode, mode_source, x2c_api_mode, x2c_api_mode_source}.  x2c_api_mode '' = fleet default (matrix rule)."""
    sec = _section(root)
    env_mode = _norm_mode(os.environ.get("NALU_DEPLOYMENT_MODE"))
    cfg_mode = _norm_mode(sec.get("mode"))
    mode, mode_src = ((env_mode, "env:NALU_DEPLOYMENT_MODE") if env_mode else
                      (cfg_mode, "qingshan.json") if cfg_mode else ("fleet", "default"))
    env_x = _norm_x2c(os.environ.get("X2C_API_MODE"))
    cfg_x = _norm_x2c(sec.get("x2c_api_mode"))
    if env_x:
        x2c, x2c_src = env_x, "env:X2C_API_MODE"
    elif cfg_x:
        x2c, x2c_src = cfg_x, "qingshan.json"
    elif mode == "single":
        x2c, x2c_src = "open", "single_mode_default"
    else:
        x2c, x2c_src = "", "fleet_default"
    return {"mode": mode, "mode_source": mode_src, "x2c_api_mode": x2c, "x2c_api_mode_source": x2c_src}


def mode(root: Path | None = None) -> str:
    try:
        return resolve(root)["mode"]
    except Exception:  # noqa: BLE001
        return "fleet"


def is_single(root: Path | None = None) -> bool:
    return mode(root) == "single"


def x2c_api_mode(root: Path | None = None) -> str:
    """'open' | 'matrix' | '' (no explicit choice: the fleet default rule in publish_x2c_matrix.matrix_mode)."""
    try:
        return resolve(root)["x2c_api_mode"]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- single-mode source rule
def user_source_files(root: Path | None = None) -> list[Path]:
    """Files the user delivered: ``<runtime>/sources/<作品>/delivered/*`` (non-empty regular files)."""
    base = (Path(root) if root else runtime()) / "sources"
    try:
        return sorted(p for p in base.glob("*/delivered/*") if p.is_file() and p.stat().st_size > 0)
    except OSError:
        return []


def source_check(root: Path | None = None) -> dict[str, Any] | None:
    """None when production may start; in single mode without a user-delivered source, the BLOCKED result."""
    if not is_single(root):
        return None
    if user_source_files(root):
        return None
    base = (Path(root) if root else runtime()) / "sources"
    return {"status": "BLOCKED", "reason": SOURCE_REQUIRED_REASON, "deployment_mode": "single",
            "expected": str(base / "<作品>" / "delivered" / "<原著文件>"),
            "hint": "单机模式：原著必须由用户提供（文件或粘贴的正文），不上网找、不自选、不写原创兜底。"
                    "请用户发原著文件，复制到 sources/<作品>/delivered/ 并按 SKILL.md §3 入库后再 start。"}


def codex_section(root: Path | None = None) -> str:
    """The start-prompt note for single mode ('' in fleet mode, so the fleet prompt is byte-identical)."""
    if not is_single(root):
        return ""
    x2c = x2c_api_mode(root)
    lines = ["## 单机模式（线主 2026-11-25）",
             "- 原著只用用户提供的文件（`$NALU_RUNTIME_ROOT/sources/<作品>/delivered/` 及其入库结果）：不上网搜索或抓取、"
             "不自选公版书、不写原创大纲兜底；派单指向的原著缺失或不全时，最后一行输出 "
             f'`NALU_STATUS: {{"state":"BLOCKED","note":"{SOURCE_REQUIRED_REASON}：<缺什么>"}}` 停下，等用户补发。']
    if x2c == "open":
        lines.append("- X2C 走旧 open-api（用户自己的 X2C 账号，无设备矩阵）：生产简报必须写 `genre`（先跑 "
                     "`publish_x2creel.py categories --lang <剧集语言>`，把选中项的显示名 name 逐字复制）和 `genre_lang`（zh|en），"
                     "派单里已有就逐字沿用。")
    return "\n".join(lines)


# ---------------------------------------------------------------- write
def write(new_mode: str, x2c: str | None = None, root: Path | None = None) -> dict[str, Any]:
    new_mode = _norm_mode(new_mode)
    if new_mode not in MODES:
        raise SystemExit(json.dumps({"status": "ERROR", "reason": "MODE_MUST_BE_single_OR_fleet"}))
    path = config_path(root)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except ValueError:
        raise SystemExit(json.dumps({"status": "ERROR", "reason": "QINGSHAN_JSON_UNPARSEABLE", "path": str(path)}))
    if not isinstance(cfg, dict):
        raise SystemExit(json.dumps({"status": "ERROR", "reason": "QINGSHAN_JSON_NOT_AN_OBJECT", "path": str(path)}))
    sec = cfg.get("deployment") if isinstance(cfg.get("deployment"), dict) else {}
    sec = dict(sec)
    sec["mode"] = new_mode
    if x2c is not None:
        x = _norm_x2c(x2c)
        if x:
            sec["x2c_api_mode"] = x
        else:  # "auto": single -> open, fleet -> the matrix default rule
            sec.pop("x2c_api_mode", None)
    elif new_mode == "single":
        sec["x2c_api_mode"] = "open"
    else:
        sec.pop("x2c_api_mode", None)  # fleet: back to the matrix default rule
    cfg["deployment"] = sec
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        perm = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        perm = 0o600
    fd, tmp = tempfile.mkstemp(prefix=".qingshan.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
        os.chmod(tmp, perm)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"status": "OK", "path": str(path), "deployment": sec, **resolve(root)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set")
    s.add_argument("mode", help="single | fleet (单机 / 集群 accepted)")
    s.add_argument("--x2c-api-mode", default=None, choices=("open", "matrix", "auto"))
    sub.add_parser("show")
    sub.add_parser("mode")
    a = ap.parse_args(argv)
    if a.cmd == "mode":
        print(mode())
        return 0
    if a.cmd == "set":
        out = write(a.mode, a.x2c_api_mode)
    else:
        out = {"status": "OK", "path": str(config_path()), **resolve()}
    if out.get("mode") == "single":
        files = user_source_files()
        out["user_source_files"] = [str(p) for p in files]
        if not files:
            out["source_note"] = SOURCE_REQUIRED_REASON
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
