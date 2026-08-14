#!/usr/bin/env python3
"""Build, mutation-test, and optionally authorize the E40 U02 V3 image package."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = Path("workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v3_low_hem_scene_authority_remediation_v1")
PROMPT = ROOT / BASE / "prompts/E40_U02_EXACT_START_FRAME_V3_LOW_HEM_AUTHORITY_PROMPT.txt"
SCENE = ROOT / BASE / "references/E40_U02_V3_LOW_CURTAIN_HEM_STATE_AUTHORITY_CROP_V1.png"
WRIST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v2_state_isolated_exact_start_frame_remediation_v1/references/E40_U02_V2_WRIST_HANDLE_SLEEVE_STATE_ISOLATED_CROP_V1.png"
PACKAGE = ROOT / BASE / "E40_U02_V3_LOW_HEM_AUTHORITY_IMAGE_MANIFEST_V1.json"
EXECUTION = ROOT / BASE / "E40_U02_V3_LOW_HEM_AUTHORITY_PAID_RETRY_MANIFEST_V1.json"
QA_DIR = ROOT / "qa/e40_preproduction_20260814/u02_v3_low_hem_authority_package_qa_v1"
ANCHOR = QA_DIR / "E40_U02_V3_ANCHOR_COUNT_GATE_V1.json"
STATIC = QA_DIR / "E40_U02_V3_STATIC_AND_NEGATIVE_GATE_V1.json"
INSTALLED = QA_DIR / "E40_U02_V3_INSTALLED_PRECHECK_V1.json"
GO_GATE = QA_DIR / "E40_U02_V3_PAID_RETRY_GO_GATE_V1.json"

SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
V1_FAILED_SHA = "6d05770f9f0324e540c1eb53f109072eae0b6510d1be99c748f0c8ee8c8e9fd6"
V2_FAILED_SHA = "87b394c6f1fb9867565db42070667c419230d58c6760cb0b02d8511e88798e74"
SCENE_SHA = "9e6fe9e5d4e610936fa34df22f20d048326981b3a01f70c2e7b8982e2a2cd161"
WRIST_SHA = "921fe9db441ac18e986cbc3015d67cb9861de2ad73528330f381230e83e530b4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def bindings() -> list[dict]:
    return [
        {
            "role": "scene",
            "entity_id": "SCENE-13-1-PHYSICAL-LOW-HEM-STATE-AUTHORITY",
            "path": str(SCENE.relative_to(ROOT)),
            "sha256": SCENE_SHA,
            "qa_status": "PASS",
            "source_kind": "SOLE_GEOMETRY_AND_CAMERA_AUTHORITY_CURTAIN_HEM_AT_BOTTOM",
            "crop_provenance": {
                "source_path": "working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png",
                "source_sha256": "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",
                "source_dimensions": [1440, 2560],
                "crop_xywh": [980, 850, 230, 616],
                "curtain_hem_intersects_bottom_border": True,
                "conflicting_state_excluded": True,
            },
        },
        {
            "role": "character",
            "entity_id": "CHAR-云妃-古装",
            "path": str(WRIST.relative_to(ROOT)),
            "sha256": WRIST_SHA,
            "qa_status": "PASS",
            "source_kind": "POSE_MATERIAL_ONLY_WRIST_HANDLE_SLEEVE_NO_HEAD_FACE_BODY_OR_OPEN_FAN",
            "crop_provenance": {
                "source_path": "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-yunfei-E40-curtain-fan-silhouette-v1-20260809.png",
                "source_sha256": "6de74d90b959178ac773a63e0fe77875ba4cd9f5dd6553da9a3ca7c7276d416e",
                "source_dimensions": [1008, 1792],
                "crop_xywh": [545, 590, 270, 390],
                "conflicting_state_excluded": True,
            },
        },
    ]


def package_manifest() -> dict:
    refs = bindings()
    prompt_sha = sha(PROMPT)
    action = "手腕刚向内收"
    return {
        "schema": "qingshan.giggle_image_manifest.v2",
        "episode": "E40",
        "created_at": now(),
        "status": "PRECOMPILED_PHYSICAL_LOW_HEM_AUTHORITY_CANDIDATE_NULL_NO_SUBMIT",
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "failure_memory": "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json#PF-032",
        "machine_gate_reports": [str(ANCHOR.relative_to(ROOT)), str(STATIC.relative_to(ROOT))],
        "consumer_contract": {
            "video_unit_id": "U02", "planned_anchor_count": 1,
            "video_model_if_later_authorized": "seedance-2.0-fast",
            "video_resolution_if_later_authorized": "720p",
            "video_submission_allowed_now": False, "human_qa_threshold": 80,
        },
        "output_dir": "working_assets/e40_preproduction_20260814/u02_exact_start_frame_v3_low_hem_authority_v1",
        "qa_dir": str(QA_DIR.relative_to(ROOT)),
        "tasks": [{
            "task_key": "E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY",
            "shot_id": "E40-U02", "video_unit_id": "U02", "tool_type": "image_generation",
            "status": "PRECOMPILED_CANDIDATE_NULL_NO_SUBMIT", "asset_role_only": False,
            "paid_submission_allowed": False, "model": "gpt-image-2-pro",
            "aspect_ratio": "9:16", "resolution": "1K", "generate_count": 1,
            "prompt_file": str(PROMPT.relative_to(ROOT)), "prompt_sha256": prompt_sha,
            "reference_images": [row["path"] for row in refs], "reference_bindings": refs,
            "source_script_sha256": SCRIPT_SHA,
            "prompt_contract": {
                "schema": "qingshan.image_prompt_contract.v2", "status": "PASS",
                "shot_id": "E40-U02", "source_script_sha256": SCRIPT_SHA,
                "source_action": action,
                "source_action_sha256": hashlib.sha256(action.encode("utf-8")).hexdigest(),
                "visible_characters": ["CHAR-云妃-古装"], "reference_bindings": refs,
                "spatial_continuity": {
                    "mode": "SAME_SPACE_CONTINUOUS", "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                    "anchor_scope": "U02_V3_LOW_HEM_BOTTOM_BORDER_WRIST_HALF_CLOSED_FAN_MACRO",
                },
            },
            "failed_asset_exclusions": [{"sha256": V1_FAILED_SHA}, {"sha256": V2_FAILED_SHA}],
            "expected_pay_upper": 11, "candidate_path": None, "candidate_sha256": None,
        }],
        "submission_policy": {
            "precheck_only": True, "authorized": False, "provider_post_allowed": False,
            "transaction_creation_allowed": False, "maximum_new_submissions": 0,
            "fresh_price_check_required_before_future_authorized_submit": True,
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    task = (data.get("tasks") or [{}])[0]
    refs = task.get("reference_bindings") or []
    policy = data.get("submission_policy") or {}
    prompt = PROMPT.read_text(encoding="utf-8")
    memory = load(ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json")
    if data.get("canonical_script_sha256") != SCRIPT_SHA or data.get("canonical_manifest_sha256") != MANIFEST_SHA:
        errors.append("CANONICAL_SHA")
    if not any(row.get("id") == "PF-032" for row in memory.get("rules", [])) or data.get("failure_memory") != "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json#PF-032":
        errors.append("PF032_BINDING")
    if task.get("task_key") != "E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY":
        errors.append("UNIQUE_V3_TASK_KEY")
    if task.get("prompt_sha256") != sha(PROMPT):
        errors.append("PROMPT_SHA")
    if task.get("paid_submission_allowed") is not False or policy.get("provider_post_allowed") is not False or policy.get("maximum_new_submissions") != 0:
        errors.append("NO_SUBMIT_POLICY")
    if [row.get("sha256") for row in refs] != [SCENE_SHA, WRIST_SHA]:
        errors.append("REFERENCE_SHA_SET")
    if task.get("reference_images") != [row.get("path") for row in refs]:
        errors.append("REFERENCE_ORDER")
    if len(refs) != 2 or [row.get("role") for row in refs] != ["scene", "character"]:
        errors.append("REFERENCE_ROLES")
    for row in refs:
        path = ROOT / str(row.get("path", ""))
        if not path.is_file() or sha(path) != row.get("sha256") or row.get("qa_status") != "PASS":
            errors.append("REFERENCE_PHYSICAL_BINDING")
    provenance = (refs[0].get("crop_provenance") if refs else {}) or {}
    if provenance.get("crop_xywh") != [980, 850, 230, 616] or provenance.get("curtain_hem_intersects_bottom_border") is not True:
        errors.append("LOW_HEM_PHYSICAL_AUTHORITY")
    if task.get("failed_asset_exclusions") != [{"sha256": V1_FAILED_SHA}, {"sha256": V2_FAILED_SHA}]:
        errors.append("FAILED_ASSET_EXCLUSIONS")
    required = ["唯一几何与机位权威", "最底部2%", "袖料像素不得超过画面面积22%", "禁止在帘幕下方生成大面积", "PF-032"]
    if any(term not in prompt for term in required):
        errors.append("MATERIAL_PROMPT_LOCK")
    return sorted(set(errors))


def build() -> int:
    if sha(ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md") != SCRIPT_SHA or sha(ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json") != MANIFEST_SHA:
        raise SystemExit("canonical SHA drift")
    if sha(SCENE) != SCENE_SHA or sha(WRIST) != WRIST_SHA:
        raise SystemExit("reference SHA drift")
    anchor = {
        "schema": "qingshan.video_unit_anchor_count_gate.v1", "recorded_at": now(), "status": "PASS",
        "episode": "E40", "video_unit_id": "U02", "planned_anchor_count": 1,
        "reason": "U02 consumes one exact start-frame anchor before any later Fast720 request.",
        "provider_calls": 0, "transactions": 0, "credits": 0,
    }
    write(ANCHOR, anchor)
    manifest = package_manifest()
    write(PACKAGE, manifest)
    canonical_errors = validate(manifest)
    cases = []

    def mutation(name: str, change) -> None:
        item = copy.deepcopy(manifest); change(item); errs = validate(item)
        cases.append({"case": name, "expected": "REJECT", "actual": "REJECT" if errs else "PASS", "reasons": errs})

    mutation("V2_TEXTURE_ONLY_SCENE_REUSE", lambda d: d["tasks"][0]["reference_bindings"][0].update({"sha256": "c5a2ff2da4239b20c3ea61fae2e8286cf334b791a036fbd3554894fd5092bf1d"}))
    mutation("UNCROPPED_SCENE_REUSE", lambda d: d["tasks"][0]["reference_bindings"][0].update({"sha256": "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88"}))
    mutation("V2_FAILED_OUTPUT_REUSE", lambda d: d["tasks"][0]["reference_bindings"][1].update({"sha256": V2_FAILED_SHA}))
    mutation("PF032_UNBOUND", lambda d: d.update({"failure_memory": "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json#PF-021"}))
    mutation("PAID_OPEN", lambda d: (d["tasks"][0].update({"paid_submission_allowed": True}), d["submission_policy"].update({"provider_post_allowed": True, "maximum_new_submissions": 1})))
    mutation("V2_TASK_KEY_REPLAY", lambda d: d["tasks"][0].update({"task_key": "E40-U02-EXACT-START-FRAME-V2-STATE-ISOLATED-RETRY1"}))
    status = "PASS" if not canonical_errors and all(row["actual"] == "REJECT" for row in cases) else "FAIL"
    report = {
        "schema": "qingshan.e40.u02.v3.low_hem_authority_static_and_negative_gate.v1",
        "recorded_at": now(), "status": status, "manifest": str(PACKAGE.relative_to(ROOT)),
        "manifest_sha256": sha(PACKAGE), "canonical_errors": canonical_errors,
        "canonical_cases_passed": 1 if not canonical_errors else 0,
        "negative_cases_rejected": sum(row["actual"] == "REJECT" for row in cases),
        "negative_case_count": len(cases), "negative_matrix": cases,
        "provider_calls": 0, "transactions": 0, "credits": 0,
    }
    write(STATIC, report)
    print(json.dumps({"status": status, "manifest_sha256": sha(PACKAGE), "static_gate_sha256": sha(STATIC), "negative_cases_rejected": report["negative_cases_rejected"]}, ensure_ascii=False))
    return 0 if status == "PASS" else 2


def prepare_paid() -> int:
    package = load(PACKAGE); installed = load(INSTALLED); static = load(STATIC)
    v2_harvest = load(ROOT / "workflow/tasks/E40_U02_V2_STATE_ISOLATED_IMAGE_HARVEST_20260814.json")
    v2_qa = load(ROOT / "qa/e40_preproduction_20260814/u02_v2_state_isolated_human_qa_v1/E40_U02_V2_STATE_ISOLATED_EXACT_START_FRAME_HUMAN_QA_V1.json")
    queue = load(ROOT / "workflow/work_queue.json")
    checks = {
        "standing_episode_authorization": queue.get("authorization_ref") == "ROGER_STANDING_EPISODE_CREDIT_CAP_10000_20260730",
        "credit_room": queue.get("e40_credits", {}).get("remaining", 0) >= 11,
        "v2_terminal_and_credit_classified": v2_harvest.get("all_terminal") is True and v2_harvest.get("credit_known_total") == 5,
        "v2_hard_failure_persisted": str(v2_qa.get("status", "")).startswith("FAIL_HARD") and v2_qa.get("failure_memory", "").endswith("#PF-032"),
        "v3_package_gate": static.get("status") == "PASS" and static.get("negative_cases_rejected") == 6,
        "v3_installed_precheck": installed.get("status") == "PASS" and installed.get("precheck_pass") == 1 and installed.get("submitted") == 0,
        "material_prompt_change": package["tasks"][0]["prompt_sha256"] != "e87916b30ab456540fab36e71a809a2b4e6cb791bbb000010607e338352f4b88",
        "physical_scene_authority_change": package["tasks"][0]["reference_bindings"][0]["sha256"] == SCENE_SHA,
    }
    if not all(checks.values()):
        raise SystemExit("paid gate failed: " + ", ".join(k for k, v in checks.items() if not v))
    gate = {
        "schema": "qingshan.e40.u02.v3.paid_retry_go_gate.v1", "recorded_at": now(), "status": "PASS",
        "authorization_ref": queue["authorization_ref"], "checks": checks,
        "prior_task_id": "e19a3950-83cc-4ebb-a116-2c6d25fdaaa1", "prior_pay": 5,
        "failure_memory": "PF-032", "maximum_new_submissions": 1,
        "transaction_required_before_post": True, "provider_calls": 0, "transactions": 0, "credits": 0,
    }
    write(GO_GATE, gate)
    execution = copy.deepcopy(package)
    execution["created_at"] = now()
    execution["status"] = "AUTHORIZED_EXACTLY_ONE_V3_PAID_RETRY_AFTER_PF032_AND_PHYSICAL_AUTHORITY_CHANGE"
    execution["machine_gate_reports"].append(str(GO_GATE.relative_to(ROOT)))
    execution["tasks"][0]["task_key"] = "E40-U02-EXACT-START-FRAME-V3-LOW-HEM-AUTHORITY-RETRY1"
    execution["tasks"][0]["status"] = "PAID_GO_EXACTLY_ONE"
    execution["tasks"][0]["paid_submission_allowed"] = True
    execution["submission_policy"] = {
        "root_only": True, "authorized": True, "provider_post_allowed": True,
        "transaction_creation_required_before_post": True,
        "bind_task_id_immediately_after_response": True,
        "maximum_new_submissions": 1, "expected_pay_upper": 11,
        "unchanged_retry_forbidden": True, "do_not_retry_on_script_error": True,
    }
    write(EXECUTION, execution)
    print(json.dumps({"status": "PASS", "execution_manifest_sha256": sha(EXECUTION), "go_gate_sha256": sha(GO_GATE)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-paid", action="store_true")
    args = parser.parse_args()
    return prepare_paid() if args.prepare_paid else build()


if __name__ == "__main__":
    raise SystemExit(main())
