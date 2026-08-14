#!/usr/bin/env python3
"""Build E39's first paid keyframe wave from admitted character and scene assets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SHA = "2726b69bd1f91ca4efbcb37cce7664cc17919f2eac7970cc49eb795318d42e0a"
MANIFEST_SHA = "f00015b954ad19f5a56d6cb116823956ee26fa8ec4742a53d443a16b77f2952a"
OUT = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805/keyframes_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


ASSETS = {
    "chenji": ("character", "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png", "e5bb8c90683120b2b02e113dc2a12b8530f8c66feaeee7657172807adb8e3373"),
    "jiaotu": ("character", "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg", "964ec3cd77fd3b51c2c5643e077cd8520c256341d00f6451a9d7044c1866d750"),
    "yunyang": ("character", "ref_images/male_yunyang_ancient_ref_20260704.jpg", "91254cf5803c0fca14577c7c658210cdc452bef0ccd06de8a11f4be4df6c7aea"),
    "ashuan": ("character", "working_assets/e38_replacement_v7_20260805/character_assets/ashuan/CHAR-E38-ashuan.jpg", "c8d5d6da7560de9040b648e0034a7624471b52d531f5e7811122340011c9a7c6"),
    "wuyun": ("character", "ref_images/cat_wuyun_reference.jpg", "7c709fe66b534747644964f9c4ca3fe593acf00eb609542c90902efc090cf101"),
    "guanchai_jia": ("character", "working_assets/e39_preproduction_20260805/character_assets_r2/E39_CHAR-E39-guanchai-jia-R2_0981b5ea-b180-4a0e-be3b-ffd67c44347c.png", "3c8b41824c6ae234e39186d143259bd9543d491aaaa3e0ba918fa442222a4abf"),
    "guanchai_yi": ("character", "working_assets/e39_preproduction_20260805/character_assets_r2/E39_CHAR-E39-guanchai-yi-R2_8a9db5a0-e6c3-4d9b-856e-6c0f3863d957.png", "0aaa79ebb32fc1bd86d1da6af62ffa8b2098ff1a93499c354cb864e2b456c396"),
    "yayi_group": ("character", "working_assets/e39_preproduction_20260805/character_assets_r2/E39_CHAR-E39-yayi-squad-1to4-R2_ed31cc2e-1ff6-4a51-8100-b05f1e244155.png", "4b9f3255922929aab296fce9be02731fc73c57730b9f58c76d7c174a78ec4893"),
    "anzhuang_group": ("character", "working_assets/e39_preproduction_20260805/character_assets/E39_CHAR-E39-jingzhao-anzhuang-group_eeb68c2f-3eb2-421c-83af-d1e4817a5f38.png", "2e55e94605d1b733cdeeee7f93a99747bdcc93ad68af073177f1ce191a16dca0"),
    "jishi_group": ("character", "working_assets/e39_preproduction_20260805/character_assets/E39_CHAR-E39-wangfu-jishi-1and2_88fec0d6-296f-41cd-8822-967a9c6f696b.png", "f22299fcb326d6cac9a2e2b5fd516317693174955d18f7942594e6751200b268"),
    "scene_12_1": ("scene", "working_assets/e39_preproduction_20260805/scene_assets_v1/SCENE-E39-12-1/SCENE-E39-12-1.jpg", "f0b5f8d18fcdece4135e60e6f02626d3e96f3f5505fa96b45a1138878213f8e6"),
    "scene_12_2": ("scene", "working_assets/e39_preproduction_20260805/scene_assets_r2/SCENE-E39-12-2-R2/SCENE-E39-12-2-R2.png", "5bbd40799543c341afaade94ed43871602266ebd7135442d79e1c468911a68ed"),
    "scene_12_3": ("scene", "working_assets/e39_preproduction_20260805/scene_assets_r2/SCENE-E39-12-3-R2/SCENE-E39-12-3-R2.jpg", "ef12242e206e9250f306031dec4d63dda2355a302b5e160d0ac7a0aa7214da0d"),
    "scene_12_4": ("scene", "working_assets/e39_preproduction_20260805/scene_assets_r2/SCENE-E39-12-4-R2/SCENE-E39-12-4-R2.jpg", "f77e18c1a1a7c07514c90c7210c931ba4a56847a1daff926cc0495352d5d174e"),
    "scene_12_5": ("scene", "working_assets/e39_preproduction_20260805/scene_assets_v1/SCENE-E39-12-5/SCENE-E39-12-5.jpg", "4eef8931b2343b058adbd6a4d48f8203d2f60e22b2f6d8a3a3363bf548f6a193"),
}


UNITS = [
    ("U01", "12-1", 15, ["chenji", "jiaotu", "yunyang", "ashuan", "yayi_group", "scene_12_1"], "两名官差正一左一右架着阿栓跨出医馆门槛一半，药簿正被靴底碾过；暗处陈迹指节收白，云羊正抽出纸符半步欲冲，皎兔侧身警戒，所有人和火把幌布都处于持续动作中。"),
    ("U02", "12-1", 11, ["chenji", "yunyang", "scene_12_1"], "官差手中的查案文书正卷起一半；暗处陈迹袖中霜线正爬上第二节指骨，另一手正松开云羊手腕，二人视线越过门口追向长街。"),
    ("U03", "12-2", 11, ["chenji", "jiaotu", "yunyang", "guanchai_jia", "guanchai_yi", "wuyun", "scene_12_2"], "长街押送队伍正从同一路线分向大道和小巷；乌云正蹬离檐瓦跃过两名官差的下风口，陈迹皎兔云羊在檐影中错位缀行，幌子和灯笼被风持续牵动。"),
    ("U04", "12-2", 12, ["chenji", "yunyang", "guanchai_jia", "guanchai_yi", "wuyun", "scene_12_2"], "陈迹指尖霜纹正托着药账日期一行移动到半途；同一动作轴后方乌云正撞落官差甲怀中卷册，云羊俯身伸手准备拾还。纸页保持清晰、留出干净可合成文字区域，禁止生成任何伪中文。"),
    ("U05", "12-2", 11, ["chenji", "jiaotu", "wuyun", "scene_12_2"], "皎兔正阖目，半透明阴神从眉心逸出并分裂到一半，两个远去街向的火光正在拉开；陈迹转头追踪两路，乌云尾尖依次指向两个方向。"),
    ("U06", "12-3", 9, ["chenji", "jiaotu", "yunyang", "guanchai_yi", "wuyun", "anzhuang_group", "scene_12_3"], "雨巷截杀已经开始：官差乙抱账封向北疾跑，四名赭褐短打暗桩正从南端和西岔墙头翻落在半空，乌云弓背厉啸，陈迹皎兔云羊同时前倾发力分兵。无黑衣暗桩，无灰衣暗桩，无人站定。"),
    ("U10", "12-4", 12, ["chenji", "jiaotu", "yunyang", "wuyun", "scene_12_4"], "密室内皎兔第二缕阴神正没入眉心一半，她的指尖正从并排账页甲移向乙；陈迹俯身观察，云羊侧后方压低重心跟随指尖，乌云尾巴正扫过案角。"),
    ("U11", "12-4", 14, ["chenji", "jiaotu", "scene_12_4"], "陈迹指尖冷雾正把账页三日错处托亮，皎兔同时展开手绘拓影到一半；纸张、手指、印纹区域和双眼全部清晰，留出准确后期文字与印纹合成区，禁止伪中文和模糊遮挡。"),
    ("U12", "12-4", 6, ["chenji", "jiaotu", "yunyang", "wuyun", "scene_12_4"], "陈迹正把拓影卷到一半并抬眼看向药簿；云羊震惊地前倾半步，皎兔呼吸未稳仍按住账页，乌云尾尖持续扫动，烛焰和纸角都在动。"),
    ("U13", "12-5", 14, ["chenji", "jiaotu", "wuyun", "jishi_group", "scene_12_5"], "雾夜王府外，换成素白直裰的陈迹正从街心迈步接近朱门，前脚正在落下；皎兔从后方追上半步伸手欲拦，乌云在肩头不安扫尾，戟士正在换岗。"),
    ("U14", "12-5", 11, ["chenji", "jiaotu", "wuyun", "scene_12_5"], "陈迹正把拓影探入贴身衣襟一半，同时抬起前脚准备登阶；皎兔仍在侧后方跟行，乌云耳朵转向门内乐音，人物均保持真实步速中的动作。"),
    ("U15", "12-5", 7, ["chenji", "jishi_group", "scene_12_5"], "素衣陈迹正踏上王府第二级石阶，身体和衣摆向前，雾气沿石阶上爬，灯笼被风推动，戟士完成换岗转身；构图预留一次由登阶驱动的升高镜头，不摆拍。"),
]


def binding(key: str) -> dict:
    role, path, expected = ASSETS[key]
    actual = sha(ROOT / path)
    if actual != expected:
        raise ValueError(f"asset SHA mismatch: {key}: {actual}")
    return {"role": role, "entity_id": key, "path": path, "sha256": expected, "qa_status": "PASS"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = []
    for unit, scene, duration, refs, action in UNITS:
        shot_id = f"E39-{unit}-A1"
        prompt = (
            "竖屏9:16，原生2K，架空宋明洛城写实动作短剧首帧。"
            "严格按参考图逐一保持人物脸、年龄、身形、发式与服装；同集角色不得换脸换衣。"
            f"剧本首帧动作：{action}"
            " 摄影机采用稳定锁定动作轴或由主体位移明确驱动的单向跟随，不摇摆、不环绕、不漫游、不慢推。"
            "前中后景都清晰可读，不用前景虚化遮住人物、证物或文字区域。"
            "所有可见人物都有持续动作或事件反应，不得冻结背景人物。"
            "真实物理比例，真实重力，真实接触点；无慢动作暗示，无英雄定格。"
            "禁止现代物件、现代服装、重复脸、黑底字幕、画内字幕、水印、标志、伪中文、乱码。"
        )
        prompt_path = OUT / f"{shot_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        bindings = [binding(key) for key in refs]
        source_action_sha = hashlib.sha256(action.encode("utf-8")).hexdigest()
        task = {
            "task_key": f"{shot_id}-STILL-V1",
            "tool_type": "image_generation",
            "scene_id": f"E39-S{scene}",
            "shot_id": shot_id,
            "video_unit_id": f"E39-{unit}",
            "video_unit_duration_seconds": duration,
            "state_index": 1,
            "state_count": 1,
            "state_role": "start_motion",
            "importance": "CRITICAL_PLOT" if unit in {"U04", "U06", "U11", "U13", "U14", "U15"} else "CONNECTOR",
            "pass_score": 80 if unit in {"U04", "U06", "U11", "U13", "U14", "U15"} else 60,
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha(prompt_path),
            "reference_images": [row["path"] for row in bindings],
            "reference_bindings": bindings,
            "prompt_contract": {
                "schema": "qingshan.image_prompt_contract.v2",
                "status": "PASS",
                "shot_id": shot_id,
                "source_script_sha256": SCRIPT_SHA,
                "source_action": action,
                "source_action_sha256": source_action_sha,
                "visible_characters": [row["entity_id"] for row in bindings if row["role"] == "character"],
                "reference_bindings": bindings,
                "spatial_continuity": {
                    "mode": "SAME_SPACE_CONTINUOUS",
                    "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "scene_id": f"E39-S{scene}",
                    "camera_design": "锁定本场人物动线和动作轴，首帧直接处于动作中，不用无动机运镜。",
                },
            },
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "status": "READY_FOR_CONCURRENT_SUBMIT",
            "source_script_sha256": SCRIPT_SHA,
            "canonical_manifest_sha256": MANIFEST_SHA,
        }
        tasks.append(task)

    gate_path = ROOT / "qa/e39_preproduction_20260805/E39_INITIAL_KEYFRAME_ANCHOR_COUNT_GATE_V1.json"
    gate = {
        "schema": "qingshan.video_unit_anchor_count_gate.v1",
        "episode": "E39",
        "status": "PASS",
        "unit_count": len(tasks),
        "planned_anchor_count": len(tasks),
        "policy": "One admitted start-motion anchor per ready unit; dependent action successors inherit exact accepted tails.",
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
    }
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "qingshan.episode_parallel_batch.v2",
        "episode": "E39",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "machine_gate_reports": [str(gate_path.relative_to(ROOT))],
        "output_dir": "working_assets/e39_keyframes_v1/candidates",
        "qa_dir": "qa/e39_keyframes_v1",
        "retry_policy": "FAILED_ITEMS_ONLY_MATERIALLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "E39_INITIAL_START_MOTION_ANCHORS",
            "video_unit_count": len(tasks),
            "planned_anchor_count": len(tasks),
            "new_image_submit_count": len(tasks),
            "dependent_anchor_count": 0,
            "all_required_anchors_planned_before_submit": True,
        },
        "tasks": tasks,
    }
    manifest_path = OUT.parent / "E39_INITIAL_KEYFRAME_WAVE_V1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
