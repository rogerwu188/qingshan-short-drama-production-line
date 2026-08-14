#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEAT = ROOT / "configs/e18_dialogue_beat_sheet_v0_20260714.json"
COVERAGE = ROOT / "configs/e18_coverage_plan_v0_20260714.json"
PROMPT = ROOT / "configs/e18_prompt_contract_v0_20260714.json"
ASSET = ROOT / "configs/e18_asset_inheritance_manifest_20260714.json"
STATIC_QA = ROOT / "configs/e18_visual_lock_static_qa_plan_20260714.json"
BATCH = ROOT / "configs/e18_source_generation_batch_manifest_v0_20260714.json"
PROMPT_ASSEMBLY = ROOT / "configs/e18_prompt_assembly_manifest_v0_20260714.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check():
    beat = load_json(BEAT)
    coverage = load_json(COVERAGE)
    prompt = load_json(PROMPT)
    asset = load_json(ASSET)
    static_qa = load_json(STATIC_QA) if STATIC_QA.exists() else None
    batch = load_json(BATCH) if BATCH.exists() else None
    prompt_assembly = load_json(PROMPT_ASSEMBLY) if PROMPT_ASSEMBLY.exists() else None

    dialogue = {item["dia_id"]: item for item in beat["dialogue_draft"]}
    exact_lines = [item["text"] for item in dialogue.values()]
    coverage_dia = set()
    coverage_assets = set()

    target_seconds_sum = 0
    for beat_item in coverage["beat_coverage"]:
        target_seconds_sum += beat_item.get("target_seconds", 0)
        for shot in beat_item.get("shots", []):
            coverage_dia.update(shot.get("dialogue", []))
            if "asset" in shot:
                coverage_assets.add(shot["asset"])

    sample_visual_hits = []
    for sample in prompt.get("sample_contracts_for_future_generation", []):
        visual = sample.get("VISUAL_PROMPT_NO_DIALOGUE_TEXT", "")
        for line in exact_lines:
            if line and line in visual:
                sample_visual_hits.append({
                    "shot_id": sample.get("shot_id"),
                    "dialogue_text": line,
                })

    forbidden_reveal_words = ["郡主", "王府关系", "靖王", "白鲤郡主"]
    reveal_hits = []
    for dia_id, item in dialogue.items():
        text = item["text"]
        for word in forbidden_reveal_words:
            if word in text:
                reveal_hits.append({"dia_id": dia_id, "word": word})

    new_assets = {item["asset_id"] for item in asset.get("new_or_variant_assets", [])}
    static_assets = {item["asset_id"] for item in static_qa.get("static_lock_items", [])} if static_qa else set()
    missing_asset_coverage = sorted(new_assets - coverage_assets)
    missing_static_qa = sorted(new_assets - static_assets)
    missing_dialogue_coverage = sorted(set(dialogue) - coverage_dia)
    batch_generation_allowed = batch.get("generation_allowed") if batch else None
    batch_dialogue = set()
    batch_static_jobs = set()
    if batch:
        for group in batch.get("batch_groups", []):
            for job in group.get("jobs", []):
                batch_dialogue.update(job.get("dialogue", []))
                if "asset_id" in job:
                    batch_static_jobs.add(job["asset_id"])
    assembly_dialogue = set()
    assembly_visual_hits = []
    non_multimodal_speaking_jobs = []
    wuyun_policy_in_assembly = False
    if prompt_assembly:
        for job in prompt_assembly.get("assembly_jobs", []):
            request_type = job.get("request_type", "")
            audio = job.get("AUDIO_PROMPT_DIALOGUE_ONLY", [])
            visual_text = json.dumps(job.get("VISUAL_PROMPT_NO_DIALOGUE_TEXT", []), ensure_ascii=False)
            for line in exact_lines:
                if line and line in visual_text:
                    assembly_visual_hits.append({"job_id": job.get("job_id"), "dialogue_text": line})
            for item in audio:
                dia_id = item.get("dialogue_id")
                if dia_id:
                    assembly_dialogue.add(dia_id)
                if dia_id == "DIA-009" and "Wuyun own stable cat voice" in item.get("tone", ""):
                    wuyun_policy_in_assembly = True
            if audio and "multimodal_video" not in request_type:
                non_multimodal_speaking_jobs.append(job.get("job_id"))

    checks = [
        {
            "name": "generation_not_allowed",
            "status": "PASS" if not beat.get("generation_allowed") and not coverage.get("generation_allowed") and not prompt.get("generation_allowed") and not asset.get("generation_allowed") else "FAIL",
        },
        {
            "name": "runtime_target_sum",
            "status": "PASS" if 165 <= target_seconds_sum <= 185 else "FAIL",
            "target_seconds_sum": target_seconds_sum,
        },
        {
            "name": "all_dialogue_ids_have_coverage",
            "status": "PASS" if not missing_dialogue_coverage else "FAIL",
            "missing": missing_dialogue_coverage,
        },
        {
            "name": "new_assets_have_coverage",
            "status": "PASS" if not missing_asset_coverage else "WARN",
            "missing": missing_asset_coverage,
        },
        {
            "name": "new_assets_have_static_visual_qa_plan",
            "status": "PASS" if static_qa and not missing_static_qa else "WARN",
            "missing": missing_static_qa,
        },
        {
            "name": "sample_visual_prompts_contain_no_exact_dialogue",
            "status": "PASS" if not sample_visual_hits else "FAIL",
            "hits": sample_visual_hits,
        },
        {
            "name": "no_baili_identity_reveal_in_dialogue",
            "status": "PASS" if not reveal_hits else "FAIL",
            "hits": reveal_hits,
        },
        {
            "name": "wuyun_own_voice_policy_present",
            "status": "PASS" if "Wuyun, own stable cat voice" in json.dumps(prompt, ensure_ascii=False) and "Wuyun must not be voiced by Chenji" in json.dumps(asset, ensure_ascii=False) else "FAIL",
        },
        {
            "name": "one_multimodal_speaking_workflow_present",
            "status": "PASS" if prompt.get("canonical_speaking_workflow") == "single_multimodal_video_request" else "FAIL",
        },
        {
            "name": "batch_manifest_present_no_submission",
            "status": "PASS" if batch and batch_generation_allowed is False else "WARN",
            "generation_allowed": batch_generation_allowed,
        },
        {
            "name": "batch_manifest_covers_dialogue",
            "status": "PASS" if batch and not sorted(set(dialogue) - batch_dialogue) else "WARN",
            "missing": sorted(set(dialogue) - batch_dialogue) if batch else sorted(set(dialogue)),
        },
        {
            "name": "batch_manifest_covers_static_lock_assets",
            "status": "PASS" if batch and not sorted(new_assets - batch_static_jobs) else "WARN",
            "missing": sorted(new_assets - batch_static_jobs) if batch else sorted(new_assets),
        },
        {
            "name": "prompt_assembly_manifest_present_no_submission",
            "status": "PASS" if prompt_assembly and prompt_assembly.get("generation_allowed") is False else "WARN",
            "generation_allowed": prompt_assembly.get("generation_allowed") if prompt_assembly else None,
        },
        {
            "name": "prompt_assembly_covers_dialogue",
            "status": "PASS" if prompt_assembly and not sorted(set(dialogue) - assembly_dialogue) else "WARN",
            "missing": sorted(set(dialogue) - assembly_dialogue) if prompt_assembly else sorted(set(dialogue)),
        },
        {
            "name": "prompt_assembly_visual_has_no_exact_dialogue",
            "status": "PASS" if not assembly_visual_hits else "FAIL",
            "hits": assembly_visual_hits,
        },
        {
            "name": "prompt_assembly_speaking_jobs_multimodal",
            "status": "PASS" if not non_multimodal_speaking_jobs else "FAIL",
            "jobs": non_multimodal_speaking_jobs,
        },
        {
            "name": "prompt_assembly_wuyun_own_voice",
            "status": "PASS" if wuyun_policy_in_assembly else "FAIL",
        },
    ]

    overall = "PASS"
    if any(item["status"] == "FAIL" for item in checks):
        overall = "FAIL"
    elif any(item["status"] == "WARN" for item in checks):
        overall = "WARN"

    return {
        "episode": "E18",
        "status": overall,
        "checked_at": "2026-07-14T21:24:00-07:00",
        "inputs": [str(BEAT), str(COVERAGE), str(PROMPT), str(ASSET), str(STATIC_QA), str(BATCH), str(PROMPT_ASSEMBLY)],
        "checks": checks,
    }


def main():
    result = check()
    out = ROOT / "qa/e18_p0_preflight_check_20260714.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
