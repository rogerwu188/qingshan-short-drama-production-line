#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEAT = ROOT / "configs/e19_dialogue_beat_sheet_v0_20260714.json"
COVERAGE = ROOT / "configs/e19_coverage_plan_v0_20260714.json"
PROMPT = ROOT / "configs/e19_prompt_contract_v0_20260714.json"
ASSET = ROOT / "configs/e19_asset_inheritance_manifest_20260714.json"
BATCH = ROOT / "configs/e19_source_generation_batch_manifest_v0_20260714.json"
ASSEMBLY = ROOT / "configs/e19_prompt_assembly_manifest_v0_20260714.json"
OUT = ROOT / "qa/e19_p0_preflight_check_20260714.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    beat, coverage, prompt, asset, batch, assembly = map(load, [BEAT, COVERAGE, PROMPT, ASSET, BATCH, ASSEMBLY])
    dialogue = {item["dia_id"]: item for item in beat["dialogue_draft"]}
    all_dialogue = set(dialogue)
    batch_dialogue = set()
    for group in batch.get("batch_groups", []):
        for job in group.get("jobs", []):
            batch_dialogue.update(job.get("dialogue", []))
    assembly_dialogue = set()
    visual_hits = []
    non_multi = []
    exact_lines = [item["text"] for item in dialogue.values()]
    for job in assembly.get("assembly_jobs", []):
        assembly_dialogue.update(job.get("dialogue", []))
        visual = job.get("visual_summary", "")
        for line in exact_lines:
            if line and line in visual:
                visual_hits.append({"job_id": job.get("job_id"), "line": line})
        if job.get("dialogue") and "multimodal_video" not in job.get("request_type", ""):
            non_multi.append(job.get("job_id"))
    target_seconds = sum(item.get("target_seconds", 0) for item in coverage.get("beat_coverage", []))
    reveal_words = ["郡主", "靖王", "白鲤郡主"]
    reveal_hits = [{"dia_id": dia, "word": word} for dia, item in dialogue.items() for word in reveal_words if word in item["text"]]
    checks = [
        {"name": "generation_not_allowed", "status": "PASS" if not any(x.get("generation_allowed") for x in [beat, coverage, prompt, asset, batch, assembly]) else "FAIL"},
        {"name": "runtime_target_sum", "status": "PASS" if 165 <= target_seconds <= 185 else "FAIL", "target_seconds_sum": target_seconds},
        {"name": "batch_covers_dialogue", "status": "PASS" if not sorted(all_dialogue - batch_dialogue) else "FAIL", "missing": sorted(all_dialogue - batch_dialogue)},
        {"name": "assembly_covers_dialogue", "status": "PASS" if not sorted(all_dialogue - assembly_dialogue) else "FAIL", "missing": sorted(all_dialogue - assembly_dialogue)},
        {"name": "assembly_visual_has_no_exact_dialogue", "status": "PASS" if not visual_hits else "FAIL", "hits": visual_hits},
        {"name": "assembly_jobs_multimodal", "status": "PASS" if not non_multi else "FAIL", "jobs": non_multi},
        {"name": "no_baili_reveal_words_in_dialogue", "status": "PASS" if not reveal_hits else "FAIL", "hits": reveal_hits},
        {"name": "fozi_action_contrast_present", "status": "PASS" if "wall-climb" in json.dumps(prompt, ensure_ascii=False).lower() and "wall climb" in json.dumps(assembly, ensure_ascii=False).lower() else "FAIL"}
    ]
    status = "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL"
    result = {"episode": "E19", "status": status, "checked_at": "2026-07-14T22:22:00-07:00", "checks": checks}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
