"""apply_runtime_fixups --language writes qingshan.json project.language, which the engine's
resolve_dialogue_language falls back to when the generation contract has no dialogue_language."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
FIXUPS = ENGINE / "skills/nalu-claude-code/scripts/apply_runtime_fixups.py"


def _resolve():
    path = ENGINE / "lines/nalu/runtime/tools/nalu_pipeline.py"
    src = path.read_text(encoding="utf-8")
    start = src.index("DIALOGUE_LANGUAGES")
    ns: dict = {}
    # only the two pure helpers are needed; avoid importing the whole pipeline (it needs a runtime root)
    lines = src[start:].split("\n", 1)[0]
    exec(lines, ns)
    for name in ("_dialogue_language_code", "resolve_dialogue_language"):
        i = src.index(f"def {name}(")
        j = src.index("\n\n\n", i)
        exec("from typing import Any\n" + src[i:j], ns)
    return ns["resolve_dialogue_language"]


def _run(root: Path, *extra: str) -> dict:
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(FIXUPS), "--runtime-root", str(root), "--cap", "2000", *extra],
                   check=True, capture_output=True)
    return json.loads((root / "qingshan.json").read_text(encoding="utf-8"))


def test_language_en_sets_project_language(tmp_path):
    cfg = _run(tmp_path, "--language", "en")
    assert cfg["project"]["language"] == "en-US"
    assert _resolve()({}, cfg) == "en"
    assert _resolve()({"dialogue_language": "zh"}, cfg) == "zh"  # the contract still wins


def test_language_omitted_leaves_chinese_default(tmp_path):
    cfg = _run(tmp_path)
    assert "language" not in (cfg.get("project") or {})
    assert _resolve()({}, cfg) == "zh"


def test_language_rerun_without_flag_keeps_english(tmp_path):
    _run(tmp_path, "--language", "en")
    cfg = _run(tmp_path)
    assert cfg["project"]["language"] == "en-US"
