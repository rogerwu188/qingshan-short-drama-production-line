#!/usr/bin/env python3
"""Build E18/E19 omni multimodal prompt packages from timeline coverage."""

from __future__ import annotations

import json
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
OUT_DIR = BASE / "workflow/prompts/e18_e19_final_omni_multimodal_candidates_v1_20260715"
QA_DIR = BASE / "qa/e18_e19_timeline_draft_v0_20260715"
PACKAGE_PATH = BASE / "configs/e18_e19_final_omni_multimodal_candidate_package_v1_20260715.json"
SUMMARY_PATH = QA_DIR / "E18_E19_FINAL_OMNI_MULTIMODAL_CANDIDATE_PACKAGE_SUMMARY_20260715.md"
PREFLIGHT_PATH = QA_DIR / "E18_E19_FINAL_OMNI_MULTIMODAL_CANDIDATE_PACKAGE_PREFLIGHT_V1_20260715.json"


VOICE_POLICY = {
    "陈迹": "cypqud0bu7t",
    "白鲤": "19uxvuf5yl1",
    "白衣少年": "male_disguise_baili_voice_policy_keep_identity_concealed",
    "乌云": "wuyun_locked_own_voice_offscreen",
    "佛子": "fozi_new_native_voice_register_if_reused",
}


NEGATIVE_PROMPT = (
    "subtitles, captions, Chinese subtitles, generated Chinese captions, burned-in subtitles, "
    "karaoke subtitles, dialogue text on screen, speaker labels, quote text, central bold dialogue text, "
    "lower-third text, bottom subtitle row, readable text, on-screen text, text overlay, watermark, "
    "caption bar, letterbox text, title card inside picture, 字幕, 文字, 标题条, 中文大字, 对白字幕, "
    "readable generated Chinese, English letters, Latin letters, modern signage, paper characters, "
    "wall characters, clothing text, object label, UI text, speech bubble, low motion talking head, "
    "frozen pose, stiff puppet, face drift, body drift, wrong face, hunched posture"
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dialogue_index(beat_sheet: dict) -> dict[str, dict]:
    return {item["dia_id"]: item for item in beat_sheet["dialogue_draft"]}


def voice_policy(speaker: str) -> str:
    return VOICE_POLICY.get(speaker, "native_offscreen_or_new_voice_required")


def line_policy(item: dict) -> dict:
    coverage = item.get("coverage", [])
    speaker = item["speaker"]
    offscreen = "offscreen_voice" in coverage or speaker in {"远处声音", "远处巡夜声", "路人低声"}
    visible_obscured = "speaker_obscured" in coverage
    if offscreen:
        lip_sync = "offscreen voice; hold reaction/evidence/space, no mouth-sync dependency"
    elif visible_obscured:
        lip_sync = "speaker is obscured; native audio timing required, visible mouth-sync only if mouth appears"
    else:
        lip_sync = "required if speaker mouth is visible in the selected shot"
    return {
        "voice_asset_id_or_policy": voice_policy(speaker),
        "tone_code": item.get("function", "playable_short_line"),
        "pace": "natural_short_drama",
        "pause": "hold the sentence before cutting",
        "lip_sync_policy": lip_sync,
        "final_method": "ONE_MULTIMODAL_VIDEO_PROMPT_WITH_SEPARATED_VISUAL_AND_AUDIO_SECTIONS",
    }


def visual_prompt(episode: str, segment: dict) -> str:
    notes = segment.get("notes", "")
    if isinstance(notes, list):
        notes_text = "; ".join(str(x) for x in notes)
    else:
        notes_text = str(notes)
    source_id = segment["source_id"]
    start = segment["timeline_start_sec"]
    end = segment["timeline_end_sec"]
    return (
        f"{episode} source group {source_id}, timeline window {start:.2f}-{end:.2f}s. "
        f"Use the locked visual intention only: {notes_text}. "
        "Keep Chenji upright when present. Hold full sentence beats with listener reactions, "
        "evidence inserts, hands, props, space bridges and natural blocking. "
        "Use cinematic xianxia short-drama lighting and grounded physical action. "
        "Do not show any readable writing, labels, subtitles, captions, title cards, UI, signs or paper text. "
        "Do not render any spoken words visually."
    )


def build_episode(episode: str, beat_file: Path, coverage_file: Path) -> tuple[list[dict], list[dict], list[dict]]:
    beat_sheet = read_json(beat_file)
    coverage = read_json(coverage_file)
    dialogue = dialogue_index(beat_sheet)
    groups: list[dict] = []
    dialogue_text_index: list[dict] = []
    guard_failures: list[dict] = []
    for dia in beat_sheet["dialogue_draft"]:
        dialogue_text_index.append(
            {
                "episode": episode,
                "dia_id": dia["dia_id"],
                "speaker": dia["speaker"],
                "text": dia["text"],
            }
        )
    for seg in coverage["segments"]:
        dialogue_ids = list(seg.get("dialogue_ids") or [])
        if not dialogue_ids:
            continue
        prompt_name = f"{episode}_{seg['order']:02d}_{seg['source_id']}_multimodal_prompt.txt"
        prompt_path = OUT_DIR / prompt_name
        audio_items = []
        for dia_id in dialogue_ids:
            dia = dialogue[dia_id]
            audio_items.append(
                {
                    "dia_id": dia_id,
                    "speaker": dia["speaker"],
                    "dialogue_text": dia["text"],
                    "timeline_window_sec": [seg["timeline_start_sec"], seg["timeline_end_sec"]],
                    **line_policy(dia),
                }
            )
        visual = visual_prompt(episode, seg)
        for item in audio_items:
            if item["dialogue_text"].replace(" ", "") in visual.replace(" ", ""):
                guard_failures.append(
                    {
                        "episode": episode,
                        "source_id": seg["source_id"],
                        "dia_id": item["dia_id"],
                        "reason": "dialogue text leaked into visual prompt",
                    }
                )
        prompt_text = "\n".join(
            [
                "VISUAL_PROMPT_NO_DIALOGUE_TEXT:",
                visual,
                "",
                "HARD_NATIVE_TEXT_BAN:",
                "The finished video frame must contain zero readable text. Spoken dialogue must be audio only.",
                "",
                "NEGATIVE_PROMPT:",
                NEGATIVE_PROMPT,
                "",
                "AUDIO_PROMPT_DIALOGUE_ONLY:",
                json.dumps(audio_items, ensure_ascii=False, indent=2),
                "",
                "MULTIMODAL_SYNC_INSTRUCTION:",
                "Generate picture, native speech, timing and any visible mouth motion together in one video-model pass. "
                "Do not create separate final dialogue audio and attempt to align it later.",
                "",
                "RHYTHM_AND_EDITING_INTENT:",
                "Follow E16 V3 sentence-hold rhythm. Do not ping-pong cut inside unfinished lines. "
                "Let each spoken unit finish before the next major cut.",
                "",
            ]
        )
        prompt_path.write_text(prompt_text, encoding="utf-8")
        groups.append(
            {
                "episode": episode,
                "source_id": seg["source_id"],
                "timeline_order": seg["order"],
                "prompt_file": str(prompt_path),
                "source_visual_baseline": seg["path"],
                "timeline_window_sec": [seg["timeline_start_sec"], seg["timeline_end_sec"]],
                "duration_window_sec": seg["duration_sec"],
                "dialogue_ids": dialogue_ids,
                "audio_dialogue_items": audio_items,
                "submission_mode": "ONE_MULTIMODAL_VIDEO_PROMPT_WITH_SEPARATED_VISUAL_AND_AUDIO_SECTIONS",
                "batch_allowed_after_preflight": True,
                "final_lock_disposition": seg.get("final_lock_disposition", "CANDIDATE_KEEP"),
                "visual_status": seg.get("visual_status"),
            }
        )
    return groups, dialogue_text_index, guard_failures


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    e18_groups, e18_dialogues, e18_failures = build_episode(
        "E18",
        BASE / "configs/e18_dialogue_beat_sheet_v0_20260714.json",
        BASE / "configs/e18_timeline_coverage_manifest_v1_20260715.json",
    )
    e19_groups, e19_dialogues, e19_failures = build_episode(
        "E19",
        BASE / "configs/e19_dialogue_beat_sheet_v0_20260714.json",
        BASE / "configs/e19_timeline_coverage_manifest_v2_20260715.json",
    )
    package = {
        "schema": "qingshan.omni_multimodal_candidate_package.v1",
        "episodes": ["E18", "E19"],
        "status": "FINAL_OMNI_MULTIMODAL_CANDIDATE_PACKAGE_V1_PREFLIGHT_READY_NOT_SUBMITTED",
        "created_at_pdt": "2026-07-15 01:42",
        "inherits_successful_flow_from": "E17 final omni multimodal package v2",
        "policy": {
            "single_multimodal_prompt_with_two_sections": True,
            "visual_section_dialogue_forbidden": True,
            "audio_section_dialogue_required": True,
            "audio_only_final_forbidden": True,
            "same_request_required_for_lipsync": True,
            "paid_submission_now": False,
            "platform_upload_order": "E17 backfill first; E18/E19 final platform uploads later in episode order",
        },
        "dialogue_text_index": e18_dialogues + e19_dialogues,
        "candidate_groups": e18_groups + e19_groups,
        "episode_counts": {
            "E18": {"candidate_groups": len(e18_groups), "dialogue_items": len(e18_dialogues)},
            "E19": {"candidate_groups": len(e19_groups), "dialogue_items": len(e19_dialogues)},
        },
    }
    PACKAGE_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = {
        "schema": "qingshan.omni_multimodal_preflight.v1",
        "package": str(PACKAGE_PATH),
        "prompt_dir": str(OUT_DIR),
        "status": "PASS" if not (e18_failures + e19_failures) else "FAIL",
        "visual_dialogue_leak_failures": e18_failures + e19_failures,
        "candidate_group_count": len(e18_groups) + len(e19_groups),
        "dialogue_item_count": len(e18_dialogues) + len(e19_dialogues),
        "expected_dialogue_counts": {"E18": 11, "E19": 18},
        "actual_dialogue_counts": {"E18": len(e18_dialogues), "E19": len(e19_dialogues)},
        "audio_only_final_forbidden": True,
    }
    PREFLIGHT_PATH.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(
        "\n".join(
            [
                "# E18/E19 Final Omni Multimodal Candidate Package V1",
                "",
                f"Status: `{preflight['status']}`.",
                "",
                "This package follows the E17 successful route: `VISUAL_PROMPT_NO_DIALOGUE_TEXT` and "
                "`AUDIO_PROMPT_DIALOGUE_ONLY` stay in the same video-model request. No standalone final dialogue "
                "audio route is allowed.",
                "",
                f"- Package: `{PACKAGE_PATH}`",
                f"- Prompt dir: `{OUT_DIR}`",
                f"- Candidate groups: `{preflight['candidate_group_count']}`",
                f"- Dialogue items: `{preflight['dialogue_item_count']}`",
                "- E18 dialogue count: `11`",
                "- E19 dialogue count: `18`",
                f"- Visual-section dialogue leaks: `{len(preflight['visual_dialogue_leak_failures'])}`",
                "",
                "Submission note: prompts may be batch-submitted after preflight, and post-generation QA must still run ASR, "
                "lipsync/manual watch, full-frame OCR, bottom-band OCR, continuity, motion and brightness gates.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps({"package": str(PACKAGE_PATH), "preflight": str(PREFLIGHT_PATH), "status": preflight["status"]}, ensure_ascii=False))
    return 0 if preflight["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
