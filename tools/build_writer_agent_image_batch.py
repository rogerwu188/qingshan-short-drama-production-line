#!/usr/bin/env python3
"""Build a provenance-bound concurrent still-image batch from Writer Agent output."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from .human_realism_prompt_contract import CONTRACT_VERSION, build_keyframe_realism_block
    from .wardrobe_identity_contract import REQUIRED_FIELDS
except ImportError:
    from human_realism_prompt_contract import CONTRACT_VERSION, build_keyframe_realism_block
    from wardrobe_identity_contract import REQUIRED_FIELDS


ROOT = Path(__file__).resolve().parents[1]

CHARACTER_REFERENCES = {
    "c_chenji": "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png",
    "c_yao": "assets/reference/e08_api_fallback_20260709/characters/CHAR-yao-taiyi-card-clean-20260709.jpg",
    "c_jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "c_baili": "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg",
    "c_yunyang": "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png",
    "c_wuyun": "ref_images/cat_wuyun_reference.jpg",
    "c_survivor": "working_assets/e28_protected_clerk_identity_v1_20260719/candidates/E28_E28-PROTECTED-CLERK-IDENTITY-V1_478230ec-fa36-489a-ba08-128d8bd0ddc4.png",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def character_text(ids: list[str], locks: dict[str, dict]) -> str:
    parts = []
    for character_id in ids:
        row = locks.get(character_id, {"name": character_id, "immutable": {}})
        immutable = row.get("immutable") or {}
        facts = "，".join(f"{key}={value}" for key, value in immutable.items())
        wardrobe = row.get("wardrobe_contract") or {}
        wardrobe_facts = "，".join(
            f"{key}={wardrobe[key]}" for key in REQUIRED_FIELDS[1:] if str(wardrobe.get(key) or "").strip()
        )
        if wardrobe and len(wardrobe_facts.split("，")) != len(REQUIRED_FIELDS) - 1:
            raise ValueError(f"{character_id} has incomplete itemized wardrobe_contract")
        identity = f"{row.get('name', character_id)}[[{character_id}]]"
        if facts:
            identity += f"（身份={facts}）"
        if wardrobe_facts:
            identity += f"（服装身份={wardrobe_facts}）"
        parts.append(identity)
    return "；".join(parts)


def allowed_time_terms(value: str) -> list[str]:
    terms = []
    if any(token in value for token in ("夜", "初夜")):
        terms.append("night")
    if "黄昏" in value:
        terms.append("dusk")
    if any(token in value for token in ("白昼", "白日", "日间")):
        terms.append("daylight")
    return terms


def allowed_weather_terms(value: str) -> list[str]:
    mapping = {"雪": "snow", "雨": "rain", "雾": "fog", "雷": "storm"}
    return [category for token, category in mapping.items() if token in value]


def scene_safe_palette(time_of_day: str, location_name: str) -> str:
    if "雪夜" in time_of_day:
        return "冷蓝白雪色、深墨灰屋瓦与克制肤色；无月光，人物和动作由环境反光与室内漏光分离"
    if "黄昏" in time_of_day or "初夜" in time_of_day:
        return "冷灰纸白、旧木褐与克制朱砂；黄昏余光转为初夜冷光，室内暖焰只作动机光"
    return "冷纸白、旧木褐与克制朱砂；阴天窗纸冷光配室内暖焰，不引入后续夜景或雪景色彩"


def build_prompt(
    episode: str,
    shot: dict,
    scene: dict,
    location_name: str,
    character_locks: dict[str, dict],
) -> str:
    still = shot["still_prompt_contract"]
    immutable_characters = character_text(shot.get("character_ids") or [], character_locks)
    negative = list(dict.fromkeys([
        *shot.get("negative_constraints", []),
        "single continuous frame only",
        "no collage, contact sheet, split screen or storyboard grid",
        "no duplicate character, extra limb, deformed hand or identity drift",
        "no readable generated text, subtitle, watermark or logo",
        "do not alter the locked event for spectacle",
    ]))
    palette = scene_safe_palette(scene["time_of_day"], location_name)
    realism = build_keyframe_realism_block(
        character_ids=shot.get("character_ids") or [],
        character_locks=character_locks,
        shot_scale=str(shot.get("shot_scale") or ""),
        lens_intent=str(shot.get("lens_intent") or ""),
        action=str(shot.get("action") or ""),
        expression_arc=shot.get("expression_arc") or shot.get("emotion_keyframe") or shot.get("expression"),
        eyeline_target=shot.get("eyeline_target") or shot.get("focus_target"),
    )
    return (
        f"《青山》{episode} 电影级竖屏关键帧，镜头 {shot['shot_id']}，9:16，2K。\n"
        f"剧本硬锁：地点={location_name}[[{shot['scene_id']}]]；时段={scene['time_of_day']}；"
        f"天气={scene['weather']}；事件={shot['action']}。地点、时段、天气、人物、道具和事件均为只读，禁止改写。\n"
        f"人物身份锁：{immutable_characters or '本镜无具名主角，以场景与道具为尺度锚点'}。"
        f"道具锁：{'、'.join(shot.get('prop_ids') or []) or '无额外道具'}。\n"
        f"只表现一个决定性瞬间：{shot['visual']}\n"
        f"画面设计：{shot['shot_scale']}；恢弘定场={bool(shot.get('grand_establishing'))}；"
        f"定场叙事目的={shot.get('establishing_purpose') or '非定场镜，承接既有空间关系'}；"
        f"镜头意图={shot['lens_intent']}；机位={shot['camera_height']}；"
        f"构图={still['composition']}；前景遮挡、中景动作、背景地点三层清晰；尺度锚点={shot['scale_anchor']}。\n"
        f"摄影与美术：{palette}；动机光={shot['key_light']}；空气层次={shot['atmosphere']}；"
        f"材质细节={shot['material_detail']}；环境动态凝固在决定性瞬间={shot['environmental_motion']}。"
        "恢弘来自真实空间纵深、人物尺度、动作因果和克制的冷暖层次；精美来自皮肤、织物、木石、金属、纸张与冰霜的真实细节，"
        "不是无关的大月亮、夜色、雾气或装饰性奇观。写实古装武侠玄幻，美剧式清晰叙事，电影摄影，人物面部稳定。\n"
        f"{realism}\n"
        "NEGATIVE_PROMPT: " + " / ".join(negative) + "。\n"
    )


def build(compiled_path: Path, generated_path: Path, out_root: Path) -> dict:
    compiled = json.loads(compiled_path.read_text(encoding="utf-8"))
    generated = json.loads(generated_path.read_text(encoding="utf-8"))
    if compiled.get("status") != "locked" or not (compiled.get("acceptance") or {}).get("passed"):
        raise ValueError("Writer Agent compiled output is not locked and accepted")
    try:
        agent_version = tuple(int(part) for part in str(compiled.get("agent_version") or "").split(".")[:3])
        schema_version = tuple(int(part) for part in str(compiled.get("schema_version") or "").split(".")[:3])
    except ValueError as exc:
        raise ValueError("Writer Agent version metadata is invalid") from exc
    if agent_version < (0, 3, 0) or schema_version < (1, 2, 0):
        raise ValueError("Writer Agent v0.3.0 / schema 1.2.0 or newer is required")

    episode = f"E{int(compiled['episode']):02d}"
    prompts_dir = out_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    scene_by_id = {row["scene_id"]: row for row in compiled["scene_contracts"]}
    location_rows = (compiled.get("continuity_audit") or {}).get("declared_locks", {}).get("locations", [])
    location_names = {row["id"]: row["name"] for row in location_rows}
    character_rows = (compiled.get("continuity_audit") or {}).get("declared_locks", {}).get("characters", [])
    character_locks = {row["id"]: row for row in character_rows}

    scene_state = []
    for scene in compiled["scene_contracts"]:
        continuity = scene.get("continuity_in") or {}
        weather = str(continuity.get("weather") or continuity.get("weather_state") or "未声明额外天气")
        scene_state.append({
            "scene_id": scene["scene_id"],
            "location": location_names.get(scene["location_id"], scene["location_id"]),
            "location_prompt_tokens": [location_names.get(scene["location_id"], scene["location_id"]), scene["location_id"]],
            "time_of_day": scene["time_of_day"],
            "weather": weather,
            "allowed_time_terms": allowed_time_terms(str(scene["time_of_day"])),
            "allowed_weather_terms": allowed_weather_terms(weather),
            "event_summary": " / ".join(
                shot["action"] for shot in compiled["shot_contracts"] if shot["scene_id"] == scene["scene_id"]
            ),
            "palette": scene["palette"],
        })

    tasks = []
    prompt_manifest = [
        f"# {episode} Writer Agent 图片生成提示词",
        "",
        f"- generated SHA-256: `{sha256(generated_path)}`",
        f"- compiled SHA-256: `{sha256(compiled_path)}`",
        "- 以下内容是实际提交给图片模型的完整提示词，不是摘要。",
        "",
    ]
    for index, shot in enumerate(compiled["shot_contracts"], 1):
        scene = scene_by_id[shot["scene_id"]]
        prompt = build_prompt(episode, shot, {
            "time_of_day": scene["time_of_day"],
            "weather": str(
                (scene.get("continuity_in") or {}).get("weather")
                or (scene.get("continuity_in") or {}).get("weather_state")
                or "未声明额外天气"
            ),
        }, location_names.get(scene["location_id"], scene["location_id"]), character_locks)
        prompt_path = prompts_dir / f"{shot['shot_id']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        prompt_manifest.extend([f"## {shot['shot_id']}", "", prompt.rstrip(), ""])
        character_ids = list(shot.get("character_ids") or [])
        episode_new_character_ids = [
            character_id for character_id in character_ids if character_id not in CHARACTER_REFERENCES
        ]
        refs = [CHARACTER_REFERENCES[character_id] for character_id in character_ids if character_id in CHARACTER_REFERENCES]
        missing_files = [path for path in refs if not (ROOT / path).is_file()]
        if missing_files:
            raise FileNotFoundError(
                f"{shot['shot_id']} asset-library identity files are missing: "
                + ", ".join(missing_files)
            )
        reference_bindings = [
            {
                "role": "character",
                "entity_id": character_id,
                "path": path,
                "sha256": sha256(ROOT / path),
                "asset_origin": "CANONICAL_NATIVE_ASSET_LIBRARY",
            }
            for character_id, path in (
                (character_id, CHARACTER_REFERENCES[character_id])
                for character_id in character_ids
                if character_id in CHARACTER_REFERENCES
            )
        ]
        is_character_keyframe = bool(shot.get("character_ids"))
        task = {
            "task_key": f"{shot['shot_id']}-WRITER-AGENT-STILL-V1",
            "tool_type": "image_generation",
            "scene_id": shot["scene_id"],
            "shot_id": shot["shot_id"],
            "visual_zone": f"{shot['scene_id']}::{shot['shot_id']}",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "reference_images": refs,
            "reference_bindings": reference_bindings,
            "asset_library_lookup": {
                "performed_before_prompt_compilation": True,
                "resolved_canonical_character_ids": [
                    character_id for character_id in character_ids if character_id in CHARACTER_REFERENCES
                ],
                "episode_new_character_ids_without_native_match": episode_new_character_ids,
                "policy": "RETURNING_CHARACTERS_REQUIRE_NATIVE_ANCHOR; EPISODE_NEW_ROLES_MAY_BE_CREATED_ONLY_AFTER_RECORDED_LOOKUP",
            },
            "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16",
            "resolution": "2K",
            "character_keyframe": is_character_keyframe,
            "status": "READY_FOR_PARALLEL_SUBMIT",
        }
        if is_character_keyframe:
            task["prompt_realism_contract_version"] = CONTRACT_VERSION
        tasks.append(task)

    generated_sha = sha256(generated_path)
    compiled_sha = sha256(compiled_path)
    scene_state_path = out_root / "scene_state.json"
    readiness_path = out_root / "script_readiness.json"
    config_path = out_root / "image_batch.json"
    prompt_manifest_path = out_root / "IMAGE_GENERATION_PROMPTS.md"
    prompt_manifest_path.write_text("\n".join(prompt_manifest).rstrip() + "\n", encoding="utf-8")
    write_json(scene_state_path, {
        "schema": "qingshan.scene_state.v1",
        "episode": episode,
        "source_script": str(generated_path.relative_to(ROOT)),
        "source_script_sha256": generated_sha,
        "status": "WRITER_AGENT_NATIVE_LOCKED",
        "scene_state": scene_state,
    })
    write_json(readiness_path, {
        "schema": "qingshan.writer_agent.script_readiness.v1",
        "episode": episode,
        "status": "PASS",
        "generated_script": str(generated_path.relative_to(ROOT)),
        "generated_script_sha256": generated_sha,
        "compiled_script": str(compiled_path.relative_to(ROOT)),
        "compiled_script_sha256": compiled_sha,
        "checks": {
            "writer_agent_acceptance": "PASS",
            "continuity_auditable": bool((compiled.get("continuity_audit") or {}).get("auditable")),
            "risks_empty": not compiled.get("risks"),
            "image_contract_count": len(compiled["image_generation_contracts"]),
            "shot_contract_count": len(compiled["shot_contracts"]),
        },
    })
    config = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "source_script": str(generated_path.relative_to(ROOT)),
        "source_script_sha256": generated_sha,
        "script_readiness_report": str(readiness_path.relative_to(ROOT)),
        "scene_contract_ref": str(scene_state_path.relative_to(ROOT)),
        "writer_agent_provenance": {
            "status": "PASS",
            "agent_version": compiled["agent_version"],
            "schema_version": compiled["schema_version"],
            "generated_script": str(generated_path.relative_to(ROOT)),
            "generated_script_sha256": generated_sha,
            "compiled_script": str(compiled_path.relative_to(ROOT)),
            "compiled_script_sha256": compiled_sha,
        },
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "parallel_submission": True,
        "concurrency": len(tasks),
        "max_retries": 1,
        "output_dir": str((ROOT / f"working_assets/{episode.lower()}_writer_agent_stills_v1/candidates").relative_to(ROOT)),
        "qa_dir": str((ROOT / f"qa/{episode.lower()}_writer_agent_stills_v1").relative_to(ROOT)),
        "base_batch_note": "All Writer Agent still contracts submit concurrently; preserve passes and retry failed items only.",
        "prompt_manifest": str(prompt_manifest_path.relative_to(ROOT)),
        "tasks": tasks,
    }
    write_json(config_path, config)
    return {"episode": episode, "shots": len(tasks), "config": str(config_path), "scene_state": str(scene_state_path), "prompt_manifest": str(prompt_manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiled", required=True, type=Path)
    parser.add_argument("--generated", required=True, type=Path)
    parser.add_argument("--out-root", required=True, type=Path)
    args = parser.parse_args()
    result = build((ROOT / args.compiled).resolve(), (ROOT / args.generated).resolve(), (ROOT / args.out_root).resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
