#!/usr/bin/env python3
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v1_20260723/video_performance_v1"
SOURCE = BASE / "E33_VIDEO_BATCH_PERFORMANCE_READY_V1.json"
PROMPT = BASE / "prompts/E33-CW-U02-PERFORMANCE-R1.txt"
OUTPUT = BASE / "E33_U02_FAILED_ONLY_PERFORMANCE_R1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    original = next(task for task in source["tasks"] if task["unit_id"] == "E33-CW-U02")
    task = copy.deepcopy(original)
    task.update({
        "task_key": "E33-CW-U02-PERFORMANCE-R1",
        "batch_id": "E33-U02-FAILED-ONLY-R1",
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "status": "READY_TO_SUBMIT",
        "retry_of_task_id": "a56d3deb-9ad9-4294-9827-7e0e09bb269c",
        "retry_reason": "REMOTE_FAILED_ZERO_CHARGE_WITH_CHANGED_PHYSICAL_ACTION_INPUT",
        "input_change": "Replaced spatially implausible cat-tail-to-three-flags action with grounded pointing, tail raise, shared eyeline, and camera reveal of three text-free guard formations.",
    })
    task["performance_spec"]["motion_beats"] = [
        {
            "start_seconds": 0.0,
            "end_seconds": 2.8,
            "subject": "Yunyang",
            "action": "Stops on wet stone, plants his right foot, extends his right arm once, and points at the locked gate while speaking.",
            "contact_point": "Both feet on wet stone; right index finger establishes an eyeline to the gate without touching it.",
            "direction": "Arm extends from chest toward the gate and then holds.",
            "end_state": "Yunyang remains grounded with his finger aimed at the locked gate.",
            "intent": "Show that all gates are locked and a direct charge is impossible.",
            "visible_causality": "The locked gate, pointing hand, and worried expression make the danger legible.",
            "expression": "Tense and worried.",
            "viewer_read": "The locked gate, pointing hand, and worried expression make the danger legible.",
        },
        {
            "start_seconds": 2.8,
            "end_seconds": 4.4,
            "subject": "Wuyun",
            "action": "Keeps all four paws planted, growls, and raises its tail once from lowered to upright as Yunyang follows its gaze.",
            "contact_point": "Four paws remain on the wet ground; tail touches no flag or person.",
            "direction": "Tail rises continuously upward and bends once to camera-right.",
            "end_state": "Wuyun holds an upright warning tail; Yunyang notices a second threat.",
            "intent": "Redirect attention from the locked gate to the surrounding factions.",
            "visible_causality": "The growl, tail raise, and shared eyeline motivate the camera reveal.",
            "expression": "Wuyun alert; Yunyang shifts from worry to realization.",
            "viewer_read": "The growl, tail raise, and shared eyeline motivate the camera reveal.",
        },
        {
            "start_seconds": 4.4,
            "end_seconds": 6.0,
            "subject": "Camera and three guard formations",
            "action": "Camera follows the shared eyeline and reveals three separated formations distinguished by gray cloaks and cool lamps, black armor and torches, and dark-red wrist guards at the gate.",
            "contact_point": "Each formation remains planted in its own zone; all flag surfaces remain plain and text-free.",
            "direction": "One smooth side move from the near group to the central group to the gate group.",
            "end_state": "Cut back to Yunyang's brief shock and Wuyun's upright warning tail.",
            "intent": "Reveal that the surrounding pursuers belong to three different camps.",
            "visible_causality": "Distinct clothing, lighting, spacing, and reaction replace labels or readable banners.",
            "expression": "Yunyang startled but thinking; Wuyun highly alert.",
            "viewer_read": "Distinct clothing, lighting, spacing, and reaction replace labels or readable banners.",
        },
    ]
    task["performance_spec"]["viewer_read"] = "The locked gate blocks escape, while three visually distinct guard formations reveal a divided encirclement without any written labels."
    task["performance_spec"]["expression_arc"] = "Yunyang moves from tense worry to realization; Wuyun remains grounded and highly alert."
    task["generation_fingerprint"] = generation_fingerprint(task)
    payload = {
        key: value for key, value in source.items() if key != "tasks"
    }
    payload.update({
        "schema": "qingshan.episode_parallel_batch.v1",
        "status": "READY_TO_SUBMIT",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "E33-U02-FAILED-ONLY-R1",
        "retry_policy": "FAILED_ITEM_ONLY_CHANGED_INPUT",
        "tasks": [task],
    })
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(OUTPUT.relative_to(ROOT)), "tasks": 1, "fingerprint": task["generation_fingerprint"]}))


if __name__ == "__main__":
    main()
