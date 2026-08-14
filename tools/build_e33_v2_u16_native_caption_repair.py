#!/usr/bin/env python3
"""Build a changed-input failed-only U16 repair for generated native captions."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/E33_VIDEO_FINAL_PERFORMANCE_V2_IDENTITY_TRANSPORT_REPAIR_REMAINING.json"
MANIFEST_SOURCE = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/E33_COMPLETE_VIDEO_PROMPT_MANIFEST_V2.json"
PROMPT_SOURCE = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/prompts/E33-CW-U16-PERFORMANCE-V2.txt"
PROMPT_OUT = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/prompts/E33-CW-U16-PERFORMANCE-V2-NATIVE-CAPTION-REPAIR-R8.txt"
CONFIG_OUT = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/E33_VIDEO_FINAL_PERFORMANCE_V2_U16_NATIVE_CAPTION_REPAIR_R8.json"
MANIFEST_OUT = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/E33_COMPLETE_VIDEO_PROMPT_MANIFEST_V2_U16_NATIVE_CAPTION_REPAIR_R8.json"


INSERT = """【画面文字绝对禁入｜本条优先于其他生成习惯】
参考音频只用于皎兔的自然普通话声线、逐字对白、口型、气息和表情，绝不把音频转写成字幕、台词字卡、人物名、识别标签、题词、UI 或任何屏幕文字。画面下半部和皎兔胸前保持纯粹的衣料、湿墙与暗洞环境，不得出现任何汉字、拼音、拉丁字母、数字、符号或伪文字。所有语言信息只存在于原生音轨和嘴唇表演中；若模型倾向自动加字幕，必须抑制该行为并保持画面无字。
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(BASE.read_text(encoding="utf-8"))
    matches = [task for task in payload["tasks"] if task["unit_id"] == "E33-CW-U16"]
    if len(matches) != 1:
        raise SystemExit("U16 source task coverage mismatch")
    original = matches[0]
    original_prompt = PROMPT_SOURCE.read_text(encoding="utf-8")
    marker = "【负面约束】"
    if marker not in original_prompt:
        raise SystemExit("U16 prompt insertion marker missing")
    repaired_prompt = original_prompt.replace(marker, INSERT + marker, 1)
    PROMPT_OUT.write_text(repaired_prompt, encoding="utf-8")

    task = copy.deepcopy(original)
    task["prompt_path"] = str(PROMPT_OUT.relative_to(ROOT))
    task["prompt_file"] = task["prompt_path"]
    task["prompt_sha256"] = sha256(PROMPT_OUT)
    task["retry_of_generation_fingerprint"] = original["generation_fingerprint"]
    task["retry_reason"] = "R7_SOURCE_FRAME_CONTAINS_MODEL_GENERATED_NATIVE_CAPTION_DESPITE_NO_TEXT_CONTRACT"
    task["changed_generation_input"] = "PROMPT_NATIVE_CAPTION_SUPPRESSION_R8"
    task["generation_fingerprint"] = generation_fingerprint(task)
    if task["generation_fingerprint"] == original["generation_fingerprint"]:
        raise SystemExit("changed-input fingerprint did not change")

    prompt_manifest = json.loads(MANIFEST_SOURCE.read_text(encoding="utf-8"))
    manifest_matches = [row for row in prompt_manifest["rows"] if row["unit_id"] == "E33-CW-U16"]
    if len(manifest_matches) != 1:
        raise SystemExit("U16 complete prompt manifest coverage mismatch")
    manifest_matches[0]["prompt_path"] = task["prompt_path"]
    manifest_matches[0]["prompt_sha256"] = task["prompt_sha256"]
    manifest_matches[0]["repair_reason"] = task["retry_reason"]
    prompt_manifest["status"] = "PASS_COMPLETE_23_OF_23_WITH_FAILED_ONLY_U16_PROMPT_REPAIR_R8"
    prompt_manifest["derived_from"] = str(MANIFEST_SOURCE.relative_to(ROOT))
    MANIFEST_OUT.write_text(json.dumps(prompt_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload["schema"] = "qingshan.episode_parallel_batch.v2"
    payload["status"] = "READY_FAILED_ONLY_U16_NATIVE_CAPTION_REPAIR_R8"
    payload["recorded_at"] = datetime.now(timezone.utc).isoformat()
    payload["submission_scope_task_keys"] = [task["task_key"]]
    payload["complete_video_prompt_manifest_ref"] = str(MANIFEST_OUT.relative_to(ROOT))
    payload["tasks"] = [task if row["unit_id"] == "E33-CW-U16" else row for row in payload["tasks"]]
    payload["repair_contract"] = {
        "failed_unit": "E33-CW-U16",
        "original_candidate_sha256": "53c3002f6fb34cb0578ed80e82dfc13ef65ab546d0de8953fa72baef27b3b932",
        "original_failure_preserved": "MODEL_GENERATED_NATIVE_CAPTION_IN_PICTURE",
        "unchanged_siblings": 22,
        "actual_input_change": task["changed_generation_input"],
        "rollback": "Restore R7 U16 source by SHA if R8 creates a worse identity, story or media result.",
    }
    CONFIG_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "config": str(CONFIG_OUT),
        "complete_video_prompt_manifest": str(MANIFEST_OUT),
        "prompt": str(PROMPT_OUT),
        "prompt_sha256": task["prompt_sha256"],
        "generation_fingerprint": task["generation_fingerprint"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
