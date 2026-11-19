"""fleet_sync reports the series' dialogue language (zh/en/ja/ko) for the fleet dashboard's language groups."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "nalu-claude-code" / "scripts"))

import fleet_sync  # noqa: E402


def _runtime(tmp_path, cfg):
    if cfg is not None:
        (tmp_path / "qingshan.json").write_text(cfg if isinstance(cfg, str) else json.dumps(cfg), encoding="utf-8")
    return tmp_path


def test_dialogue_language_from_project_language(tmp_path):
    for value, code in (("zh-CN", "zh"), ("en-US", "en"), ("ja-JP", "ja"), ("ko-KR", "ko"),
                        ("ja", "ja"), ("KO_kr", "ko"), ("zh-Hans", "zh")):
        rt = _runtime(tmp_path, {"project": {"language": value}})
        assert fleet_sync.dialogue_language(rt) == code, value


def test_dialogue_language_unknown_or_missing_is_none(tmp_path):
    assert fleet_sync.dialogue_language(tmp_path) is None  # no qingshan.json
    for cfg in ({}, {"project": {}}, {"project": "x"}, [], {"project": {"language": "fr-FR"}},
                {"project": {"language": "japanese"}}, "{not json"):
        assert fleet_sync.dialogue_language(_runtime(tmp_path, cfg)) is None, cfg


def test_build_status_carries_dialogue_language(tmp_path):
    engine, runtime = tmp_path / "engine", tmp_path / "runtime"
    engine.mkdir()
    runtime.mkdir()
    (runtime / "qingshan.json").write_text(json.dumps({"project": {"language": "ko-KR"}}), encoding="utf-8")
    cp = SimpleNamespace(roots=lambda: (engine, runtime), current_episode=lambda: "",
                         read_json=lambda path: {})
    status, _blocker, _tail = fleet_sync.build_status(cp, {"action": "IDLE"})
    assert status["dialogue_language"] == "ko"
