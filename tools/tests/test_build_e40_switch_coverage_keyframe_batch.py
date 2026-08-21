import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import build_e40_switch_coverage_keyframe_batch as target  # noqa: E402


def test_compile_batch_keeps_space_and_filters_visible_identity(tmp_path: Path) -> None:
    output = tmp_path / "batch.json"
    prompts = tmp_path / "prompts"
    result = target.compile_batch(target.DEFAULT_PLAN, target.DEFAULT_BASE, prompts, output)

    assert result["provider_post_allowed"] is False
    assert result["credits"] == 0
    assert result["machine_gate_reports"]
    assert len(result["tasks"]) == 8
    assert all(row["status"] == "READY_FOR_PRECHECK_NO_PROVIDER_POST" for row in result["tasks"])
    assert all(row["provider_post_allowed"] is False for row in result["tasks"])
    by_id = {row["coverage_id"]: row for row in result["tasks"]}
    macro = by_id["E40-COV-FOUR-MARKS-MACRO"]
    assert macro["visible_characters"] == []
    assert not [row for row in macro["reference_bindings"] if row["role"] == "character"]
    assert macro["episode_global_space_map_id"] == "EGSM-E40-WANGFU-SEQUENCE-001"

    reaction = by_id["E40-COV-BAILI-EYELINE-REACTION"]
    identities = [row for row in reaction["reference_bindings"] if row["role"] == "character"]
    assert [row["entity_id"] for row in identities] == ["CHAR-白鲤-古装"]
    assert identities[0]["asset_origin"] == "CANONICAL_NATIVE_REGISTRY"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PRECHECK_READY_NO_PROVIDER_POST"
