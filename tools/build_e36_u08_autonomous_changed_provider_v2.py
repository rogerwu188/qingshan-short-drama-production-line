#!/usr/bin/env python3
"""Build a materially changed U08 provider input under Roger's standing authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE_DIR = BASE / "recovery_10000_20260730/u08_video"
OUT = BASE / "autonomous_recovery_20260731/u08_changed_provider_v2"
QA = ROOT / "qa/e36_agentcut_20260730/u08_changed_provider_v2_runtime"
CONFIG = OUT / "E36_U08_CHANGED_PROVIDER_V2_BATCH.json"
PROMPT = OUT / "E36-CW-U08-CHANGED-PROVIDER-V2.txt"
PROMPT_MANIFEST = OUT / "E36_U08_CHANGED_PROVIDER_V2_COMPLETE_PROMPT_MANIFEST.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads((SOURCE_DIR / "E36_U08_RECOVERY_EPISODE_PARALLEL_BATCH_V1.json").read_text(encoding="utf-8"))
    task = deepcopy(source["tasks"][0])
    image_paths = task["reference_images"]
    image_ids = task["reference_image_asset_ids"]
    image_sequence = task["reference_image_sequence"]

    prompt = """VISUAL_PROMPT_NO_DIALOGUE_TEXT:
E36 U08，5秒，9:16，720p，真实速度连续单镜头。以@图片1为动作中途首帧：云羊在左侧贴肩护送递信人向画面左后方奔跑，皎兔右手抓紧递信人后领，陈迹在外侧跨步开路；以@图片2为终态：同一四人进入人潮遮挡但仍在奔跑，无人回头或站定。@图片3只锁云羊17岁身份。
【实体绑定】[[yunyang]]云羊=17岁男性可见说话者；[[chenji]]陈迹=17岁男性外侧开路；[[jiaotu]]皎兔=18岁女性持续抓后领；[[rescued_messenger]]递信人=被护送对象；[[scene_west_market_execution_ground]]西市法场。
【天气硬合同】weather=HEAT_NOON_DRY_DUST。午时硬光、干燥尘烟、低饱和灰褐旧木色为唯一视觉世界；禁雨、湿地、夜色和无来源奇幻光。
【光影与色彩】动机光为正上方偏右的午时硬日光，面部保持可读暖灰肤色和短硬阴影；低饱和灰褐、炭黑、旧木黄和纸张灰白为主色，飞尘仅受逆侧光勾边。
镜头1【32mm关系中广景，摄影机沿撤离方向向画面左后方轻微手持跟移】{对白：云羊两句短促撤离指令}<音效：急促脚步、纸张翻飞、人群惊呼、衣料摩擦>连续覆盖以下动作，不切镜，不重置姿势。
0.00-0.30秒：四人已在奔跑，云羊前臂持续贴住递信人肩胸，皎兔五指持续抓住后领并拉出布料张力，陈迹外侧开路；方向始终由刑台向画面左后方。终态为云羊侧脸和完整嘴部清楚可见并吸气。
0.30-1.35秒：云羊不减速，只说一次第一句；前臂接触不断，末字后闭口。
1.35-1.65秒：云羊闭口换气并转肩推引，皎兔保持后领接触，陈迹继续开路。
1.65-3.45秒：云羊边跑边只说一次第二句，身体仍朝撤离方向，声音投向同伴；末字后闭口并收回视线。
3.45-5.00秒：无人说话，四人穿过前景百姓肩背形成的动态遮挡，持续奔跑抵达@图片2终态。
环境生命：白纸持续翻飞，百姓哗然后退、伸手抓纸并横切前景，脚步扬尘，衣摆和发丝受热风牵引；背景不得冻结。古代午时法场，低饱和灰褐和旧木色，禁雨、夜色、现代物件、生成文字、字幕、水印。禁止慢镜、摆拍、看镜头、换脸、换性别、换衣、接触点断裂、第五名主角、肢体粘连、血腥。
AUDIO_PROMPT_DIALOGUE_ONLY:
全部对白由视频模型原生生成自然中文普通话，只允许云羊发声。0.30-1.35秒，云羊急促克制地说：“换出来了！”；1.65-3.45秒，云羊低声坚决地说：“走——别回头！”破折号仅为短气口。必须逐字准确，口型、唇齿、下颌、喉部、胸腹气息、眉眼表情与起止时间同步。陈迹、皎兔、递信人全程闭口喘息。禁旁白、画外音、后配音、改字、漏字、重复、串词和字幕烧录。
"""
    OUT.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt, encoding="utf-8")

    task.update({
        "task_key": "E36-CW-U08-CHANGED-PROVIDER-V2-10000",
        "source_id": "E36-CW-U08-CHANGED-PROVIDER-V2-10000",
        "batch_id": "E36-U08-CHANGED-PROVIDER-V2-10000",
        "model": "seedance-2.0-fast",
        "prompt_path": rel(PROMPT),
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha(PROMPT),
        "reference_images": image_paths,
        "reference_image_asset_ids": image_ids,
        "reference_image_sequence": image_sequence,
        "planned_reference_image_count": 2,
        "provider_input_change": "FAST_MODEL_PLUS_REWRITTEN_FOCUSED_PROMPT_WITH_EXISTING_VERIFIED_MULTIMODAL_BINDINGS",
        "status": "READY_TO_SUBMIT",
        "max_retries": 0,
    })
    config = deepcopy(source)
    config.update({
        "status": "READY_FOR_SUPERVISOR_PRECHECK",
        "source_cl2x": "CL2X-868",
        "source_mailbox_sha256": "fb53a702323f2388252f1d4c1e97d99dcf113200672498eb52db6a0301996747",
        "video_credit_limit": 10000,
        "episode_paid_credits_before": 7968,
        "output_dir": "working_assets/e36_recovery_10000_20260730/u08_changed_provider_v2",
        "qa_dir": rel(QA),
        "complete_video_prompt_manifest_ref": rel(PROMPT_MANIFEST),
        "tasks": [task],
        "authority_ref": "workflow/approvals/ROGER_AUTONOMOUS_COMPLETION_NO_ROUTINE_AUTH_REQUESTS_20260731.json",
    })

    manifest = json.loads((BASE / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V25.json").read_text(encoding="utf-8"))
    row = next(row for row in manifest["rows"] if row["unit_id"] == "U08")
    row.update({"prompt_path": rel(PROMPT), "prompt_sha256": sha(PROMPT)})
    write_json(PROMPT_MANIFEST, manifest)
    write_json(CONFIG, config)
    print(json.dumps({"config": rel(CONFIG), "config_sha256": sha(CONFIG), "prompt": rel(PROMPT), "prompt_sha256": sha(PROMPT), "projected_credits": 80}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
