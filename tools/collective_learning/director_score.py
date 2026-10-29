"""DIRECTOR_SCORE_V1: per-episode director evaluation, coverage, efficiency and next-episode plan.

Three results are kept apart on purpose (requirement section 6.1):

* the viewer-experience score (this rubric),
* the technical severe-defect list and user-accepted imperfections,
* the production-efficiency report.

None of them is a publication authority or a redo threshold, and none feeds the
existing audience/final-cut gates.  An evaluation is bound to one final video
sha256 + timeline version + rubric version/sha + evaluator identity; re-cutting
or changing the rubric creates a NEW evaluation, old ones are kept and the two
are not compared unless the caller explicitly asks for a re-cut comparison.

Coverage is honest: a reviewer who only saw a contact sheet cannot score sound,
motion continuity or pacing, so those dimensions are UNASSESSED and the total is
null (never zero-filled, never renormalised).

Pure functions plus a thin CLI; no network, no provider calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):  # pragma: no cover -- CLI run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.collective_learning import contracts as c
else:
    from . import contracts as c

ROOT = Path(__file__).resolve().parents[2]
RUBRIC_PATH = ROOT / "configs" / "DIRECTOR_SCORE_V1.json"
RUBRIC_VERSION = "DIRECTOR_SCORE_V1"
PLAN_SCHEMA = "qingshan.collective.next_episode_plan.v1"
EFFICIENCY_SCHEMA = "qingshan.collective.production_efficiency.v1"
PLAN_INDEX_RELPATH = "reports/director_evaluation"

EXPECTED_WEIGHTS = {
    "narrative_causality": 20,
    "pacing_information": 15,
    "performance_interaction": 20,
    "composition_camera_motivation": 15,
    "editing_action_continuity": 15,
    "sound_dialogue": 10,
    "emotion_continuation": 5,
}
EVALUATOR_ROLES = ("CREATOR_SELF", "INDEPENDENT")
COVERAGE_MODES = ("CONTINUOUS_AV", "SEGMENTED_AV", "CONTACT_SHEET", "FRAMES", "NONE")
# Still images cannot show sound, motion continuity or whole-film rhythm.
STILL_ONLY_UNASSESSABLE = ("pacing_information", "editing_action_continuity", "sound_dialogue")
UNASSESSED = "UNASSESSED"
MIN_REASON_CHARS = 12

# Keys a blind first-round independent reviewer must not see.
CREATOR_ONLY_KEYS = frozenset({
    "creator_evaluation", "creator_evaluation_id", "creator_score", "creator_scores", "self_evaluation",
    "self_score", "target_score", "expected_score", "previous_total", "fix_rationale", "fix_reason",
    "repair_rationale",
})

# Section 7.2 responsibility rows.  Stage labels are responsibilities, not a line's stage numbers.
OWNER_INTERFACES = {
    "writing_input": "WRITING",
    "storyboard_directing_intent": "DIRECTING",
    "identity_voice_prep": "ASSET_PREP",
    "keyframe_compile_previs": "KEYFRAME",
    "video_submit": "VIDEO_SUBMIT",
    "post_edit_sound": "POST",
    "final_review_close": "FINAL_REVIEW",
}
DIMENSION_OWNER = {
    "narrative_causality": "writing_input",
    "pacing_information": "storyboard_directing_intent",
    "performance_interaction": "storyboard_directing_intent",
    "composition_camera_motivation": "keyframe_compile_previs",
    "editing_action_continuity": "post_edit_sound",
    "sound_dialogue": "post_edit_sound",
    "emotion_continuation": "writing_input",
}
DIMENSION_VERIFICATION = {
    "narrative_causality": "下一集独立评审在对应时码确认目标、阻力与转折原因可从画面或行动读出",
    "pacing_information": "下一集成片逐段核对每段是否带来新信息/行动/情绪变化，并记录无目的停顿数",
    "performance_interaction": "下一集对白段核对视线目标与交谈对象一致、听者有反应，并记录不一致单元数/适用单元数",
    "composition_camera_motivation": "关键帧与成片核对关键主体可读、运动有动机，并记录无动机重复运动的单元数/适用单元数",
    "editing_action_continuity": "逐一检查所有相邻接点的空间方向与动作阶段，记录断裂接点数/接点总数",
    "sound_dialogue": "全片带声观看核对台词完整与归属，记录截断或缺失句数/台词总句数",
    "emotion_continuation": "独立评审确认结尾期待由前文铺垫，并记录观众反馈",
}
WAIT_CATEGORIES = ("queue", "dependency", "review", "budget", "provider_generation")
ATTEMPT_OUTCOMES = ("ACCEPTED", "ACCEPTED_IMPERFECTION", "REJECTED", "NO_RESULT", "TIMEOUT",
                    "PENDING_REVIEW", "CANCELLED")


# --------------------------------------------------------------------------- rubric
def load_rubric(path: Path | None = None) -> dict[str, Any]:
    """Load and integrity-check the frozen rubric; the file sha256 is attached as ``rubric_sha256``."""
    path = Path(path or RUBRIC_PATH)
    raw = path.read_bytes()
    rubric = json.loads(raw.decode("utf-8"))
    failures: list[str] = []
    if rubric.get("rubric_version") != RUBRIC_VERSION:
        failures.append(f"RUBRIC_VERSION_UNEXPECTED:{rubric.get('rubric_version')}")
    dims = rubric.get("dimensions") or []
    weights = {d.get("key"): d.get("weight") for d in dims}
    if weights != EXPECTED_WEIGHTS:
        failures.append("RUBRIC_WEIGHTS_CHANGED_WITHOUT_NEW_VERSION")
    if sum(int(w or 0) for w in weights.values()) != 100:
        failures.append("RUBRIC_WEIGHTS_MUST_SUM_TO_100")
    for dim in dims:
        anchors = dim.get("anchors") or {}
        if sorted(anchors) != [str(i) for i in range(6)] or not all(str(v).strip() for v in anchors.values()):
            failures.append(f"RUBRIC_ANCHORS_INCOMPLETE:{dim.get('key')}")
        examples = dim.get("examples") or {}
        if not str(examples.get("positive") or "").strip() or not str(examples.get("negative") or "").strip():
            failures.append(f"RUBRIC_EXAMPLES_INCOMPLETE:{dim.get('key')}")
    if sorted((rubric.get("generic_anchors") or {})) != [str(i) for i in range(6)]:
        failures.append("RUBRIC_GENERIC_ANCHORS_INCOMPLETE")
    if failures:
        raise c.ContractError(failures)
    rubric["rubric_sha256"] = hashlib.sha256(raw).hexdigest()
    return rubric


# --------------------------------------------------------------------------- coverage
def assess_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    """Decide what the evidence can support.

    Returns ``{"status": FULL|PARTIAL|UNASSESSED, "unassessable_dimensions": [...],
    "total_assessable": bool, "reasons": [...]}``.
    """
    mode = coverage.get("mode")
    if mode not in COVERAGE_MODES:
        raise c.ContractError([f"COVERAGE_MODE_INVALID:{mode}"])
    reasons: list[str] = []
    unassessable: set[str] = set()
    total_assessable = True
    if mode == "NONE":
        return {"mode": mode, "status": UNASSESSED, "unassessable_dimensions": sorted(EXPECTED_WEIGHTS),
                "total_assessable": False, "reasons": ["NO_MEDIA_ACCESS"]}
    if mode in ("CONTACT_SHEET", "FRAMES"):
        unassessable.update(STILL_ONLY_UNASSESSABLE)
        reasons.append(f"STILL_IMAGES_ONLY:{mode}")
    else:
        if coverage.get("with_sound") is not True:
            unassessable.add("sound_dialogue")
            reasons.append("NO_SOUND_PASS")
        if coverage.get("whole_film_pacing_pass") is not True:
            unassessable.add("pacing_information")
            reasons.append("NO_WHOLE_FILM_PACING_PASS")
        if mode == "SEGMENTED_AV":
            expected = list(coverage.get("segments_expected") or [])
            joins = list(coverage.get("joins_expected") or [])
            if not expected:
                reasons.append("SEGMENT_LIST_REQUIRED")
                total_assessable = False
            missing_seg = sorted(set(expected) - set(coverage.get("segments_reviewed") or []))
            missing_join = sorted(set(joins) - set(coverage.get("joins_reviewed") or []))
            if missing_seg:
                reasons.append("SEGMENTS_NOT_REVIEWED:" + ",".join(map(str, missing_seg)))
                total_assessable = False
            if missing_join:
                reasons.append("JOINS_NOT_REVIEWED:" + ",".join(map(str, missing_join)))
                unassessable.add("editing_action_continuity")
    if unassessable:
        total_assessable = False
    status = "FULL" if total_assessable and not reasons else "PARTIAL"
    return {"mode": mode, "status": status, "unassessable_dimensions": sorted(unassessable),
            "total_assessable": total_assessable, "reasons": reasons}


# --------------------------------------------------------------------------- evaluation
def _validate_evaluator(evaluator: Any, failures: list[str]) -> dict[str, str]:
    if not isinstance(evaluator, dict):
        failures.append("EVALUATOR_MUST_BE_OBJECT")
        return {}
    if evaluator.get("role") not in EVALUATOR_ROLES:
        failures.append(f"EVALUATOR_ROLE_INVALID:{evaluator.get('role')}")
    for key in ("model", "prompt_version", "process_id"):
        if not str(evaluator.get(key) or "").strip():
            failures.append(f"EVALUATOR_{key.upper()}_REQUIRED")
    return {k: str(evaluator.get(k) or "") for k in ("role", "model", "prompt_version", "process_id")}


def _validate_timecodes(rows: Any, video_sha256: str, label: str, failures: list[str]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        failures.append(f"{label}:EVIDENCE_MUST_BE_LIST")
        return clean
    for index, row in enumerate(rows):
        local: list[str] = []
        c.validate_timecode(row, index, local)
        if isinstance(row, dict) and row.get("timeline") not in (None, "FINAL_CUT"):
            local.append(f"TIMECODE_MUST_BE_FINAL_CUT:{index}")
        if isinstance(row, dict) and c.is_sha256(row.get("video_sha256")) and row["video_sha256"] != video_sha256:
            local.append(f"TIMECODE_BOUND_TO_OTHER_VIDEO:{index}")
        failures.extend(f"{label}:{code}" for code in local)
        if not local:
            clean.append({"video_sha256": row["video_sha256"], "timeline": "FINAL_CUT",
                          "start_ms": row["start_ms"], "end_ms": row["end_ms"]})
    return clean


def _clean_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [re.sub(r"\s+", " ", str(v)).strip() for v in value if str(v).strip()]


def evaluate(*, episode_id: str, video_sha256: str, timeline_version: str, evaluator: dict[str, Any],
             coverage: dict[str, Any], dimensions: dict[str, Any],
             severe_defects: list[dict[str, Any]] | None = None,
             accepted_imperfections: list[dict[str, Any]] | None = None,
             declared_inputs: list[str] | None = None, review_round: int = 1,
             creator_evaluation_ids: Iterable[str] = (), rubric: dict[str, Any] | None = None,
             tenant_id: str | None = None, line_id: str | None = None, run_id: str | None = None,
             evaluated_at: str | None = None, supersedes: str | None = None) -> dict[str, Any]:
    """Build a validated, immutable DirectorEvaluation record.  Raises ``ContractError`` with every code."""
    rubric = rubric or load_rubric()
    failures: list[str] = []
    if not c.is_sha256(video_sha256):
        failures.append("FINAL_VIDEO_SHA256_REQUIRED")
    if not str(timeline_version or "").strip():
        failures.append("TIMELINE_VERSION_REQUIRED")
    if not str(episode_id or "").strip():
        failures.append("EPISODE_ID_REQUIRED")
    who = _validate_evaluator(evaluator, failures)
    cov = assess_coverage(coverage)

    # Independent first round is blind to the creator's view.
    inputs = [str(x) for x in (declared_inputs or [])]
    if who.get("role") == "INDEPENDENT" and int(review_round) == 1:
        creator_ids = set(creator_evaluation_ids)
        leaked = sorted(set(inputs) & creator_ids)
        if leaked:
            failures.append("INDEPENDENT_ROUND1_SAW_CREATOR_EVALUATION:" + ",".join(leaked))
        leaked_keys = sorted(k for k in inputs if k in CREATOR_ONLY_KEYS)
        if leaked_keys:
            failures.append("INDEPENDENT_ROUND1_SAW_CREATOR_FIELDS:" + ",".join(leaked_keys))

    if not isinstance(dimensions, dict):
        failures.append("DIMENSIONS_MUST_BE_OBJECT")
        dimensions = {}
    unknown = sorted(set(dimensions) - set(EXPECTED_WEIGHTS))
    failures.extend(f"DIMENSION_UNKNOWN:{key}" for key in unknown)
    weights = {d["key"]: int(d["weight"]) for d in rubric["dimensions"]}
    clean_dims: dict[str, dict[str, Any]] = {}
    for key in EXPECTED_WEIGHTS:
        row = dimensions.get(key) or {}
        if not isinstance(row, dict):
            failures.append(f"DIMENSION_ROW_INVALID:{key}")
            row = {}
        level = row.get("level", UNASSESSED)
        if level in (None, UNASSESSED):
            clean_dims[key] = {"weight": weights[key], "level": UNASSESSED, "points": None,
                               "reasons": str(row.get("reasons") or "").strip() or None, "evidence": [],
                               "strengths": [], "weaknesses": []}
            continue
        if key in cov["unassessable_dimensions"]:
            failures.append(f"DIMENSION_NOT_ASSESSABLE_FROM_COVERAGE:{key}")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 5:
            failures.append(f"DIMENSION_LEVEL_INVALID:{key}")
            continue
        reasons = re.sub(r"\s+", " ", str(row.get("reasons") or "")).strip()
        if len(reasons) < MIN_REASON_CHARS:
            failures.append(f"DIMENSION_REASONS_TOO_SHORT:{key}")
        evidence = _validate_timecodes(row.get("evidence"), video_sha256, f"DIMENSION_EVIDENCE:{key}", failures)
        if not evidence:
            failures.append(f"DIMENSION_EVIDENCE_TIMECODE_REQUIRED:{key}")
        clean_dims[key] = {"weight": weights[key], "level": level,
                           "points": weights[key] * level / 5, "reasons": reasons, "evidence": evidence,
                           "strengths": _clean_text_list(row.get("strengths")),
                           "weaknesses": _clean_text_list(row.get("weaknesses"))}

    defects: list[dict[str, Any]] = []
    for index, row in enumerate(severe_defects or []):
        if not isinstance(row, dict) or not str(row.get("description") or "").strip():
            failures.append(f"SEVERE_DEFECT_INVALID:{index}")
            continue
        if row.get("severity") not in ("P0", "P1"):
            failures.append(f"SEVERE_DEFECT_SEVERITY_INVALID:{index}")
        ev = _validate_timecodes(row.get("evidence") or [], video_sha256, f"SEVERE_DEFECT:{index}", failures)
        owner = row.get("owner_interface") or "final_review_close"
        if owner not in OWNER_INTERFACES:
            failures.append(f"SEVERE_DEFECT_OWNER_INVALID:{index}")
        defects.append({"severity": row.get("severity"), "description": str(row["description"]).strip(),
                        "category": row.get("category"), "owner_interface": owner, "evidence": ev})

    accepted: list[dict[str, Any]] = []
    for index, row in enumerate(accepted_imperfections or []):
        if not isinstance(row, dict) or not str(row.get("description") or "").strip():
            failures.append(f"ACCEPTED_IMPERFECTION_INVALID:{index}")
            continue
        if row.get("outcome") not in (None, "ACCEPTED_IMPERFECTION"):
            # A human accepting a flaw is not a fix; the record cannot say otherwise.
            failures.append(f"ACCEPTED_IMPERFECTION_CANNOT_BE_RELABELLED:{index}:{row.get('outcome')}")
        if not str(row.get("accepted_by") or "").strip():
            failures.append(f"ACCEPTED_IMPERFECTION_ACCEPTED_BY_REQUIRED:{index}")
        ev = _validate_timecodes(row.get("evidence") or [], video_sha256, f"ACCEPTED_IMPERFECTION:{index}", failures)
        accepted.append({"description": str(row["description"]).strip(), "accepted_by": row.get("accepted_by"),
                         "outcome": "ACCEPTED_IMPERFECTION", "evidence": ev})
    if failures:
        raise c.ContractError(failures)

    assessed = [k for k, v in clean_dims.items() if v["level"] != UNASSESSED]
    missing = [k for k in EXPECTED_WEIGHTS if k not in assessed]
    complete = not missing and cov["total_assessable"]
    total = round(sum(clean_dims[k]["points"] for k in EXPECTED_WEIGHTS)) if complete else None
    if not assessed or cov["status"] == UNASSESSED:
        status = UNASSESSED
    elif complete and cov["status"] == "FULL":
        status = "COMPLETE"
    else:
        status = "PARTIAL"
    record: dict[str, Any] = {
        "schema": c.EVALUATION_SCHEMA,
        "schema_version": c.SCHEMA_VERSION,
        "evaluation_id": c.new_uuid(),
        "episode_id": episode_id,
        "tenant_id": tenant_id,
        "line_id": line_id,
        "run_id": run_id,
        "final_video_sha256": video_sha256,
        "timeline_version": timeline_version,
        "rubric_version": rubric["rubric_version"],
        "rubric_sha256": rubric["rubric_sha256"],
        "evaluator": who,
        "review_round": int(review_round),
        "declared_inputs": inputs,
        "evaluated_at": evaluated_at or c.now_iso(),
        "coverage": {**cov, "declared": coverage},
        "status": status,
        "dimensions": clean_dims,
        "total": total,
        "comparable": total is not None,
        "missing_dimensions": missing,
        "total_method": "round(sum(weight*level/5)); null unless all seven dimensions are assessed",
        "severe_defects": defects,
        "accepted_imperfections": accepted,
        "authority": {"publication": False, "redo_threshold": False, "feeds_existing_gates": False},
    }
    if supersedes:
        record["supersedes"] = supersedes
    record["content_sha256"] = c.digest({k: v for k, v in record.items() if k != "content_sha256"})
    return record


def build_blind_review_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Copy of a review packet with every creator-only key removed (recursively)."""
    stripped: list[str] = []

    def _strip(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key in CREATOR_ONLY_KEYS:
                    stripped.append(f"{path}.{key}")
                    continue
                out[key] = _strip(item, f"{path}.{key}")
            return out
        if isinstance(value, list):
            return [_strip(item, f"{path}[{i}]") for i, item in enumerate(value)]
        return value

    clean = _strip(packet, "$")
    clean["blind_round"] = 1
    clean["stripped_keys"] = stripped
    return clean


def disagreement(self_eval: dict[str, Any], independent_eval: dict[str, Any]) -> dict[str, Any]:
    """Per-dimension delta between a creator self-evaluation and an independent one.  Neither is modified."""
    if self_eval["evaluator"]["role"] != "CREATOR_SELF" or independent_eval["evaluator"]["role"] != "INDEPENDENT":
        raise c.ContractError(["DISAGREEMENT_NEEDS_SELF_AND_INDEPENDENT"])
    if self_eval["final_video_sha256"] != independent_eval["final_video_sha256"]:
        raise c.ContractError(["DISAGREEMENT_ACROSS_DIFFERENT_VIDEOS"])
    rows = {}
    for key in EXPECTED_WEIGHTS:
        a, b = self_eval["dimensions"][key]["level"], independent_eval["dimensions"][key]["level"]
        rows[key] = {"creator_self": a, "independent": b,
                     "delta": (a - b) if isinstance(a, int) and isinstance(b, int) else None}
    return {"self_evaluation_id": self_eval["evaluation_id"],
            "independent_evaluation_id": independent_eval["evaluation_id"],
            "dimensions": rows,
            "total": {"creator_self": self_eval["total"], "independent": independent_eval["total"]}}


def compare(a: dict[str, Any], b: dict[str, Any], *, recut: bool = False) -> dict[str, Any]:
    """Compare two evaluations only when they are on the same scale.

    Refuses across rubric versions/shas and evaluator model/prompt versions, and
    across different final videos unless ``recut=True`` (an explicit re-cut comparison).
    """
    reasons: list[str] = []
    if (a["rubric_version"], a["rubric_sha256"]) != (b["rubric_version"], b["rubric_sha256"]):
        reasons.append("RUBRIC_VERSION_DIFFERS")
    for key in ("model", "prompt_version"):
        if a["evaluator"].get(key) != b["evaluator"].get(key):
            reasons.append(f"EVALUATOR_{key.upper()}_DIFFERS")
    if a["final_video_sha256"] != b["final_video_sha256"] and not recut:
        reasons.append("DIFFERENT_FINAL_VIDEO_NOT_DECLARED_RECUT")
    if a["total"] is None or b["total"] is None:
        reasons.append("TOTAL_NOT_COMPARABLE")
    if reasons:
        return {"comparable": False, "reasons": reasons}
    return {"comparable": True, "reasons": [], "recut": recut, "total_delta": b["total"] - a["total"],
            "dimension_delta": {k: b["dimensions"][k]["level"] - a["dimensions"][k]["level"]
                                for k in EXPECTED_WEIGHTS}}


class EvaluationArchive:
    """Write-once evaluation files: ``<root>/<episode>/<evaluation_id>.json``.  Nothing is overwritten."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def save(self, evaluation: dict[str, Any]) -> Path:
        path = self.root / evaluation["episode_id"] / f"{evaluation['evaluation_id']}.json"
        text = json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != text:
                raise c.ContractError([f"EVALUATION_ID_CONFLICT:{evaluation['evaluation_id']}"])
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return path

    def list(self, episode_id: str) -> list[dict[str, Any]]:
        folder = self.root / episode_id
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))] \
            if folder.is_dir() else []
        return sorted(rows, key=lambda r: r["evaluated_at"])


# --------------------------------------------------------------------------- efficiency
def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def interval_union_seconds(intervals: Iterable[tuple[Any, Any]]) -> float:
    """Length of the union of [start, end) intervals: concurrent work is not summed."""
    spans = sorted((_seconds(s), _seconds(e)) for s, e in intervals)
    total, cur_s, cur_e = 0.0, None, None
    for start, end in spans:
        if end < start:
            raise c.ContractError(["INTERVAL_END_BEFORE_START"])
        if cur_e is None or start > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = start, end
        else:
            cur_e = max(cur_e, end)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def efficiency_report(*, episode_id: str, attempts: list[dict[str, Any]], confirmed_spend: float,
                      accepted_minutes: float, unresolved_cost_risk: float = 0.0,
                      task_intervals: list[dict[str, Any]] | None = None,
                      wait_intervals: list[dict[str, Any]] | None = None,
                      spend_unit: str = "credits") -> dict[str, Any]:
    """Production efficiency, with every denominator shown (section 9)."""
    failures: list[str] = []
    for index, row in enumerate(attempts):
        if row.get("outcome") not in ATTEMPT_OUTCOMES:
            failures.append(f"ATTEMPT_OUTCOME_INVALID:{index}:{row.get('outcome')}")
        if not isinstance(row.get("attempt"), int) or row["attempt"] < 1:
            failures.append(f"ATTEMPT_NUMBER_INVALID:{index}")
    for index, row in enumerate(wait_intervals or []):
        if row.get("category") not in WAIT_CATEGORIES:
            failures.append(f"WAIT_CATEGORY_INVALID:{index}:{row.get('category')}")
    if failures:
        raise c.ContractError(failures)
    first = [r for r in attempts if r["attempt"] == 1]
    with_result = [r for r in first if r["outcome"] not in ("NO_RESULT", "TIMEOUT", "CANCELLED")]
    reviewed = [r for r in with_result if r["outcome"] != "PENDING_REVIEW" and r.get("reviewed", True)]
    normal = [r for r in reviewed if r["outcome"] == "ACCEPTED"]
    imperfect = [r for r in reviewed if r["outcome"] == "ACCEPTED_IMPERFECTION"]
    counts = {
        "first_submissions": len(first),
        "with_result": len(with_result),
        "no_result_or_timeout": sum(1 for r in first if r["outcome"] in ("NO_RESULT", "TIMEOUT")),
        "pending_review": sum(1 for r in first if r["outcome"] == "PENDING_REVIEW"),
        "cancelled": sum(1 for r in first if r["outcome"] == "CANCELLED"),
        "reviewed": len(reviewed),
        "accepted_normal": len(normal),
        "accepted_imperfection": len(imperfect),
    }
    rate = (len(normal) + len(imperfect)) / len(reviewed) if reviewed else None
    coverage = len(reviewed) / len(with_result) if with_result else None
    cost_per_minute = (confirmed_spend / accepted_minutes) if accepted_minutes > 0 else None
    waits = {cat: interval_union_seconds((w["start"], w["end"]) for w in (wait_intervals or [])
                                         if w["category"] == cat) for cat in WAIT_CATEGORIES}
    tasks = [(t["start"], t["end"]) for t in (task_intervals or [])]
    return {
        "schema": EFFICIENCY_SCHEMA,
        "episode_id": episode_id,
        "first_pass_usable": {
            **counts,
            "rate": rate,
            "rate_status": "OK" if rate is not None else "NOT_COMPUTABLE",
            "review_coverage": coverage,
            "definition": "(accepted_normal + accepted_imperfection) / reviewed first submissions with a result",
        },
        "cost": {
            "confirmed_spend": confirmed_spend,
            "unresolved_cost_risk": unresolved_cost_risk,
            "spend_unit": spend_unit,
            "accepted_minutes": accepted_minutes,
            "cost_per_usable_minute": cost_per_minute,
            "cost_per_usable_minute_status": "OK" if cost_per_minute is not None else "NOT_COMPUTABLE",
        },
        "time": {
            "wall_seconds": interval_union_seconds(tasks) if tasks else None,
            "summed_task_seconds_not_wall_time": sum(_seconds(e) - _seconds(s) for s, e in tasks) if tasks else None,
            "wait_seconds_by_category": waits,
        },
    }


# --------------------------------------------------------------------------- next-episode plan
def next_episode_plan(evaluations: list[dict[str, Any]], *, episode_id: str, next_episode_id: str | None = None,
                      efficiency: dict[str, Any] | None = None, candidate_refs: list[str] | None = None,
                      max_targets: int = 3) -> dict[str, Any]:
    """1-3 improvement targets, a keep-list and the reasons nothing stronger can be claimed.

    Independent evaluations are preferred over self-evaluation.  The plan never
    asks for a higher total than the last episode: lowering the recurrence of one
    confirmed defect while keeping the rest is a legitimate target.
    """
    max_targets = max(1, min(3, int(max_targets)))
    bound = [e for e in evaluations if e["episode_id"] == episode_id]
    independent = [e for e in bound if e["evaluator"]["role"] == "INDEPENDENT"]
    source = independent or bound
    unconfirmed: list[str] = []
    if not bound:
        unconfirmed.append("NO_EVALUATION_FOR_EPISODE")
    elif not independent:
        unconfirmed.append("ONLY_CREATOR_SELF_EVALUATION: targets are hypotheses until independently reviewed")
    if len({e["evaluator"]["model"] for e in source}) <= 1 and source:
        unconfirmed.append("SINGLE_EVALUATOR_MODEL: same-model sessions are not independent aesthetic sources")
    for e in source:
        if e["status"] != "COMPLETE":
            unconfirmed.append(f"EVALUATION_{e['status']}:{e['evaluation_id']}:missing={','.join(e['missing_dimensions'])}")

    targets: list[dict[str, Any]] = []
    for e in source:
        for defect in e["severe_defects"]:
            owner = defect["owner_interface"]
            targets.append({"priority": 0, "target": f"降低复发：{defect['description']}",
                            "dimension": None, "owner_interface": owner, "stage": OWNER_INTERFACES[owner],
                            "verification_method": "下一集在适用单元统计该缺陷复发率 = 出现单元数/已审阅适用单元数",
                            "evidence_refs": [{"evaluation_id": e["evaluation_id"], **tc} for tc in defect["evidence"]]})
    scored: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {}
    for e in source:
        for key, row in e["dimensions"].items():
            if isinstance(row["level"], int):
                scored.setdefault(key, []).append((row["level"], row, e))
    ranked = sorted(scored.items(), key=lambda kv: (min(x[0] for x in kv[1]), -EXPECTED_WEIGHTS[kv[0]]))
    for key, rows in ranked:
        level, row, e = min(rows, key=lambda x: x[0])
        if level >= 4 and targets:
            break
        owner = DIMENSION_OWNER[key]
        weakness = (row["weaknesses"] or [row["reasons"]])[0]
        targets.append({"priority": 1, "target": weakness, "dimension": key, "observed_level": level,
                        "owner_interface": owner, "stage": OWNER_INTERFACES[owner],
                        "verification_method": DIMENSION_VERIFICATION[key],
                        "evidence_refs": [{"evaluation_id": e["evaluation_id"], **tc} for tc in row["evidence"]]})
    targets = sorted(targets, key=lambda t: t["priority"])[:max_targets]

    keep: list[dict[str, Any]] = []
    for key, rows in scored.items():
        level, row, e = max(rows, key=lambda x: x[0])
        if level >= 4:
            keep.append({"dimension": key, "level": level,
                         "preserve": (row["strengths"] or [row["reasons"]])[0],
                         "evidence_refs": [{"evaluation_id": e["evaluation_id"], **tc} for tc in row["evidence"]]})
    keep.sort(key=lambda r: (-r["level"], r["dimension"]))
    return {
        "schema": PLAN_SCHEMA,
        "episode_id": episode_id,
        "next_episode_id": next_episode_id,
        "generated_at": c.now_iso(),
        "source_evaluation_ids": [e["evaluation_id"] for e in source],
        "targets": targets,
        "keep_list": keep,
        "score_policy": {"higher_total_required": False,
                         "note": "目标是降低已确认缺陷的复发率并保留有效做法，不要求下一集总分更高。"},
        "cost_and_wait": (efficiency or {}).get("cost"), "wait": (efficiency or {}).get("time"),
        "candidate_experience_refs": list(candidate_refs or []),
        "unconfirmed_because": unconfirmed,
        "authority": {"paid_redo": False, "publication": False},
    }


def _episode_key(episode_id: str) -> tuple[str, int]:
    match = re.match(r"^(.*?)(\d+)$", str(episode_id))
    return (match.group(1), int(match.group(2))) if match else (str(episode_id), -1)


def plan_index_dirs(runtime_root: Path) -> list[Path]:
    root = Path(runtime_root)
    return [root / "runtime" / PLAN_INDEX_RELPATH, root / PLAN_INDEX_RELPATH]


def publish_plan(runtime_root: Path, plan: dict[str, Any]) -> Path:
    """Write the plan into the runtime-root index that :func:`latest_improvement_plan` reads."""
    root = Path(runtime_root)
    folder = plan_index_dirs(root)[0] if (root / "runtime").is_dir() else plan_index_dirs(root)[1]
    path = folder / f"{plan['episode_id']}_NEXT_EPISODE_PLAN.json"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def latest_improvement_plan(runtime_root: Path, before_episode: str) -> dict[str, Any] | None:
    """The most recent plan from an episode before ``before_episode`` (same id prefix), or None."""
    prefix, number = _episode_key(before_episode)
    best: tuple[int, str, dict[str, Any]] | None = None
    for folder in plan_index_dirs(Path(runtime_root)):
        for path in folder.glob("*_NEXT_EPISODE_PLAN.json") if folder.is_dir() else []:
            try:
                plan = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if plan.get("schema") != PLAN_SCHEMA:
                continue
            p_prefix, p_number = _episode_key(plan.get("episode_id", ""))
            if p_prefix != prefix or p_number >= number or p_number < 0:
                continue
            key = (p_number, str(plan.get("generated_at") or ""))
            if best is None or key > best[:2]:
                best = (*key, {**plan, "_path": str(path)})
    return best[2] if best else None


# --------------------------------------------------------------------------- report
def render_markdown(evaluation: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    rubric_dims = {d["key"]: d["label"] for d in load_rubric()["dimensions"]}
    e = evaluation
    total = e["total"] if e["total"] is not None else f"不可比较（缺：{', '.join(e['missing_dimensions'])}）"
    lines = [
        f"# {e['episode_id']} 导演评估（{e['rubric_version']}）", "",
        "## 成片与评审",
        f"- 成片 sha256：`{e['final_video_sha256']}`；时间线版本：{e['timeline_version']}",
        f"- 观看方式：{e['coverage']['mode']}；覆盖：{e['coverage']['status']}"
        + (f"（{'; '.join(e['coverage']['reasons'])}）" if e['coverage']['reasons'] else ""),
        f"- 评审：{e['evaluator']['role']} / {e['evaluator']['model']} / 提示词 {e['evaluator']['prompt_version']}",
        f"- 评估状态：{e['status']}；总分：{total}", "",
        "## 分项分数", "", "| 维度 | 权重 | 档位 | 证据时码 | 理由 |", "|---|---:|---:|---|---|",
    ]
    for key, row in e["dimensions"].items():
        stamps = ", ".join(f"{t['start_ms']}–{t['end_ms']}ms" for t in row["evidence"]) or "—"
        lines.append(f"| {rubric_dims.get(key, key)} | {row['weight']} | {row['level']} | {stamps} | "
                     f"{(row['reasons'] or '—').replace('|', '/')} |")
    lines += ["", "## 优点与缺点"]
    for key, row in e["dimensions"].items():
        for s in row["strengths"]:
            lines.append(f"- 优点（{rubric_dims.get(key, key)}）：{s}")
        for w in row["weaknesses"]:
            lines.append(f"- 缺点（{rubric_dims.get(key, key)}）：{w}")
    lines += ["", "## 技术严重问题"]
    lines += [f"- [{d['severity']}] {d['description']}" for d in e["severe_defects"]] or ["- 无"]
    lines += ["", "## 用户已接受的瑕疵（ACCEPTED_IMPERFECTION，不等于已修复）"]
    lines += [f"- {a['description']}（接受人：{a['accepted_by']}）" for a in e["accepted_imperfections"]] or ["- 无"]
    if plan:
        lines += ["", "## 下一集改进目标"]
        for t in plan["targets"]:
            lines.append(f"- {t['target']} → 负责接口 `{t['owner_interface']}`（{t['stage']}）；验证：{t['verification_method']}")
        lines += ["", "## 保留清单（已经有效的做法）"]
        lines += [f"- {k['preserve']}（{rubric_dims.get(k['dimension'], k['dimension'])} {k['level']} 档）"
                  for k in plan["keep_list"]] or ["- 暂无"]
        lines += ["", "## 尚不能确认的原因"]
        lines += [f"- {u}" for u in plan["unconfirmed_because"]] or ["- 无"]
        if plan.get("cost_and_wait"):
            cost = plan["cost_and_wait"]
            lines += ["", "## 成本与等待",
                      f"- 已确认支出：{cost['confirmed_spend']} {cost['spend_unit']}；未决费用风险：{cost['unresolved_cost_risk']}",
                      f"- 每分钟可用成片成本：{cost['cost_per_usable_minute'] if cost['cost_per_usable_minute'] is not None else '不可计算'}"]
    lines += ["", "> 本报告不是发布授权，也不是重做门槛；身份、对白与授权安全检查独立运行。", ""]
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- thin CLI
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rubric", help="print the frozen rubric with its sha256")
    ev = sub.add_parser("evaluate", help="validate an evaluation input JSON and write evaluation + report")
    ev.add_argument("--input", type=Path, required=True,
                    help="JSON with keys accepted by evaluate() (episode_id, video_sha256, ...)")
    ev.add_argument("--out-json", type=Path, required=True)
    ev.add_argument("--out-md", type=Path)
    ev.add_argument("--plan-out", type=Path)
    lp = sub.add_parser("latest-plan")
    lp.add_argument("--runtime-root", type=Path, required=True)
    lp.add_argument("--before-episode", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "rubric":
            print(json.dumps(load_rubric(), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "latest-plan":
            print(json.dumps(latest_improvement_plan(args.runtime_root, args.before_episode), ensure_ascii=False,
                             indent=2))
            return 0
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        record = evaluate(**payload)
        _write_json(args.out_json, record)
        plan = next_episode_plan([record], episode_id=record["episode_id"])
        if args.plan_out:
            _write_json(args.plan_out, plan)
        if args.out_md:
            args.out_md.write_text(render_markdown(record, plan), encoding="utf-8")
        print(json.dumps({"status": record["status"], "evaluation_id": record["evaluation_id"],
                          "total": record["total"]}, ensure_ascii=False))
        return 0
    except (c.ContractError, ValueError, OSError, TypeError) as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
