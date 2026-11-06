#!/usr/bin/env python3
"""Script-stage independent review (AI_REVIEW) — the pre-lock read, not an audience score.

Why this exists
---------------
Before 2026-11-01 nothing read a script except the writer who wrote it.  The
first judgement a nalu episode received was the audience score after it had been
paid for and cut.  The offline pilot (PILOT_RESULT.md) had two independent
readers read equal-length synopses only, and both preferred the arc-cut version
of E11-E13 in every episode — 6/6 under both reading orders.  That is a signal
worth having before the script is locked, even though the writers were not
audience members.

Line owner 2026-11-01: review before script lock and before paid prep; REUSE the
existing review system (``vlm_review_protocol.py``); writer and reviewer
separated; marked AI_REVIEW — never audience feedback; routine issues are
answered by the writer and never block; only a MAJOR creative disagreement
escalates.

How it plugs in
---------------
``script_review`` is a kind of the existing protocol (registered in
``nalu_qa_common.KINDS``, ``vlm_review_protocol.QUESTIONNAIRES`` and
``OBSERVED_FIELDS``).  A request carries ONE item — the anonymised synopsis —
bound by sha256 like every other review.  Validation, reviewer identity, the
answers template and the submitted-record shape are the protocol's.

What this module adds:
  ``anonymise``   strip episode/version/chapter labels and the preamble before
                  handing the text to a reviewer that must not know whose arc it is.
  ``validate``    the script questionnaire is validated WITHOUT the media verdict
                  rule: a script review never writes PASS and never REJECTs.  Its
                  item verdict is REVIEWED, or INCOMPLETE while a confusion point
                  is unanswered.
  ``respond``     apply the writer's per-point response (REVISED / EXPLAINED /
                  DISAGREE_ESCALATED) and produce the report.  The report stays
                  INCOMPLETE until every point has an answer.
  ``materialise`` the hook the protocol calls on submit: write the pending report.

Non-blocking by default
-----------------------
Nothing here refuses a stage.  ``report.blocking`` is false unless the caller
passes ``--blocking`` (a config switch the line owner has not turned on), and a
rare DISAGREE_ESCALATED is the only thing that leaves the writer's hands.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import nalu_paths as _np  # noqa: E402

TOOL_ID = "script_review.v1"
KIND = "script_review"
POLICY_ID = "WRITER_CAPABILITY_V1"
REVIEW_METHOD_SCRIPT = "AI_REVIEW"
REPORT_SCHEMA = "nalu.script_review_report.v1"
RESPONSES_SCHEMA = "nalu.script_review_writer_responses.v1"
MIN_RESPONSE_CHARS = 8

REVIEWS_ROOT = Path(f"{_np.RUNTIME_ROOT}") / "runtime" / "reviews"

#: The writer's answer to one confusion point.  REVISED means the script changed;
#: EXPLAINED means it did not and here is why; DISAGREE_ESCALATED is the only
#: value that leaves the writer's hands (line owner 2026-11-01: only a MAJOR
#: creative disagreement escalates to the line owner).
RESPONSE_DISPOSITIONS = ("REVISED", "EXPLAINED", "DISAGREE_ESCALATED")

#: A script review's item verdict is never PASS: the reviewer did not admit
#: anything, it raised questions the writer must answer.
VERDICT_REVIEWED = "REVIEWED"
VERDICT_INCOMPLETE = "INCOMPLETE"

_SCENE_HEADER = re.compile(r"^##\s+(?P<body>.+)$")
_EPISODE_LABEL = re.compile(r"\bE\d{2,3}\b")
_VERSION = re.compile(r"\bv\d{1,3}\b", re.IGNORECASE)
_CHAPTER = re.compile(r"\bch\d{1,4}\b", re.IGNORECASE)
_CHINESE_EPISODE = re.compile(r"第\s*\d+\s*集")
_CN_CHAPTER = re.compile(r"第\s*[\d一二三四五六七八九十百]+\s*章")
_FILE_STEM = re.compile(r"[A-Za-z0-9_\-]*NARRATIVE[_-]?CANONICAL[A-Za-z0-9_\-]*", re.IGNORECASE)
_THREAD_LABEL = re.compile(r"线\s*[A-Z]")
_LOC_ID = re.compile(r"\bLOC-[A-Z0-9][A-Z0-9_\-]*")
_TIME_ID = re.compile(r"\bTIME-[A-Z0-9][A-Z0-9_\-]*")


# --------------------------------------------------------------------------- anonymisation


def _neutral(text: str) -> str:
    text = _FILE_STEM.sub("", text)
    text = _EPISODE_LABEL.sub("EP", text)
    text = _VERSION.sub("", text)
    text = _CHAPTER.sub("the source", text)
    text = _CHINESE_EPISODE.sub("", text)
    text = _CN_CHAPTER.sub("the source", text)
    text = _THREAD_LABEL.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def anonymise(narrative: str) -> dict[str, Any]:
    """Return ``{synopsis, scene_labels, dropped_preamble_lines}``.

    The preamble — everything before the first ``## `` scene header — is where
    the writer records the episode number, version, the authorising order, the
    source chapter, the season position and 「观众已知，本集不得复证」.  All of it
    would bias an independent read, so all of it is dropped and the number of
    dropped non-empty lines is reported back with the request.
    """
    lines = str(narrative or "").replace("\r\n", "\n").split("\n")
    body_start = next((index for index, line in enumerate(lines) if _SCENE_HEADER.match(line)), None)
    if body_start is None:
        return {"synopsis": _neutral("\n".join(lines)).strip() + "\n",
                "scene_labels": [], "dropped_preamble_lines": 0}
    dropped = [line for line in lines[:body_start] if line.strip()]
    loc_map: dict[str, str] = {}
    time_map: dict[str, str] = {}
    labels: list[str] = []

    def _loc(match: re.Match[str]) -> str:
        key = match.group(0)
        loc_map.setdefault(key, f"L{len(loc_map) + 1}")
        return loc_map[key]

    def _time(match: re.Match[str]) -> str:
        key = match.group(0)
        time_map.setdefault(key, f"T{len(time_map) + 1}")
        return time_map[key]

    out: list[str] = []
    scene_index = 0
    for line in lines[body_start:]:
        header = _SCENE_HEADER.match(line)
        if not header:
            out.append(_neutral(_TIME_ID.sub(_time, _LOC_ID.sub(_loc, line))))
            continue
        scene_index += 1
        label = f"S{scene_index:02d}"
        parts = [part.strip() for part in header.group("body").split("｜") if part.strip()]
        fields: list[str] = []
        for part in parts[1:]:
            if _LOC_ID.fullmatch(part):
                fields.append(_loc(_LOC_ID.match(part)))  # type: ignore[arg-type]
            elif _TIME_ID.fullmatch(part):
                fields.append(_TIME_ID.sub(_time, part))
            elif _THREAD_LABEL.search(part):
                continue
            else:
                fields.append(_neutral(part))
        labels.append(label)
        out.append(("## " + "｜".join([label, *fields])) if fields else ("## " + label))
    return {"synopsis": "\n".join(out).strip() + "\n", "scene_labels": labels,
            "dropped_preamble_lines": len(dropped)}


def synopsis_for(episode: str, narrative: Path | str | None = None) -> tuple[Path, dict[str, Any], str]:
    """Write the anonymised synopsis into the episode's review folder and return it."""
    from nalu_qa_common import QaPaths

    path = Path(narrative) if narrative else QaPaths(episode).narrative
    if not path.is_file():
        raise SystemExit(f"SCRIPT_REVIEW_NARRATIVE_MISSING:{path}")
    result = anonymise(path.read_text(encoding="utf-8"))
    if not result["synopsis"].strip():
        raise SystemExit(f"SCRIPT_REVIEW_SYNOPSIS_EMPTY:{path}")
    target = REVIEWS_ROOT / episode / f"{episode}_{KIND}_synopsis.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result["synopsis"], encoding="utf-8")
    return target, result, str(path)


# --------------------------------------------------------------------------- validation


def validate(request: dict[str, Any], request_sha: str,
             answers: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate script-review answers.  Same structure as the protocol, no PASS/REJECT.

    Reused from the media validator: schema, reviewer identity, request sha,
    enumerated answers, a real observation, the observed lists, and a
    confusion-point list per item.  Deliberately NOT reused: the media rule that
    any FAIL answer is a REJECT.  Here a FAIL answer is a confusion point, and a
    confusion point is work for the writer, not a refusal.
    """
    import vlm_review_protocol as vrp
    from nalu_qa_common import MIN_OBSERVATION_CHARS, REVIEWER_ID, SCHEMA_ANSWERS, TEMPLATE_MARKER

    failures: list[str] = []
    questions = request.get("questionnaire") or {}
    if answers.get("schema") != SCHEMA_ANSWERS:
        failures.append(f"answers_schema_invalid:{answers.get('schema')}")
    if answers.get(TEMPLATE_MARKER):
        failures.append("answers_are_the_untouched_template_no_review_happened")
    if str(answers.get("reviewer") or "") != REVIEWER_ID:
        failures.append(f"reviewer_not_{REVIEWER_ID}:{answers.get('reviewer')}")
    if not str(answers.get("reviewed_at") or "").strip():
        failures.append("reviewed_at_missing")
    if str(answers.get("request_sha256") or "") != request_sha:
        failures.append(f"request_sha256_mismatch:declared={answers.get('request_sha256') or 'MISSING'}")

    rows = answers.get("items")
    if not isinstance(rows, list) or not rows:
        failures.append("answer_items_missing")
        return failures, []

    by_id = {row["item_id"]: row for row in request.get("items") or []}
    seen: list[str] = []
    verdicts: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        item_id = str(row.get("item_id") or "")
        prefix = f"item_{index}:{item_id or 'UNKNOWN'}"
        if item_id not in by_id:
            failures.append(f"{prefix}:unknown_item_id")
            continue
        if item_id in seen:
            failures.append(f"{prefix}:duplicate_item")
            continue
        seen.append(item_id)
        item_failures: list[str] = []

        given = row.get("answers") if isinstance(row.get("answers"), dict) else {}
        if not isinstance(row.get("answers"), dict):
            item_failures.append("answers_not_object")
        for key, spec in questions.items():
            if key not in given:
                item_failures.append(f"answer_missing:{key}")
            elif given[key] is None:
                item_failures.append(f"answer_null:{key}")
            elif str(given[key]) not in spec["enum"]:
                item_failures.append(f"answer_not_enumerated:{key}={given[key]!r}")

        observation = str(row.get("observation") or "").strip()
        if len(observation) < MIN_OBSERVATION_CHARS:
            item_failures.append(f"observation_too_short:{len(observation)}<{MIN_OBSERVATION_CHARS}")

        observed = row.get("observed") if isinstance(row.get("observed"), dict) else {}
        if not isinstance(row.get("observed"), dict):
            item_failures.append("observed_not_object")
        vocabulary = by_id[item_id].get("closed_vocabulary") or {}
        for field, vocab_key in (vrp.OBSERVED_FIELDS[KIND] or {}).items():
            if field not in observed or observed[field] is None:
                item_failures.append(f"observed_missing:{field}")
                continue
            values = observed[field]
            if not isinstance(values, list):
                item_failures.append(f"observed_not_list:{field}")
                continue
            allowed = vocabulary.get(vocab_key)
            if vocab_key == "free" or allowed is None:
                continue
            for value in values:
                text = str(value)
                if text not in allowed and not text.startswith(vrp.UNDECLARED_PREFIX):
                    item_failures.append(f"observed_outside_closed_vocabulary:{field}:{text}")

        points = row.get("confusion_points")
        if not isinstance(points, list):
            item_failures.append("confusion_points_missing_use_empty_list_when_none")
            points = []
        for p_index, point in enumerate(points, 1):
            if not isinstance(point, dict):
                item_failures.append(f"confusion_point_{p_index}_not_object")
                continue
            if not str(point.get("question") or "").strip():
                item_failures.append(f"confusion_point_{p_index}_question_missing")
            if len(str(point.get("why") or "").strip()) < MIN_OBSERVATION_CHARS:
                item_failures.append(f"confusion_point_{p_index}_why_too_short")
            scene = str(point.get("scene") or "").strip()
            labels = by_id[item_id].get("scene_labels") or []
            if scene and labels and scene not in labels:
                item_failures.append(f"confusion_point_{p_index}_scene_unknown:{scene}")

        failures.extend(f"{prefix}:{value}" for value in item_failures)
        verdicts.append({
            "item_id": item_id,
            "verdict": VERDICT_REVIEWED if not item_failures else VERDICT_INCOMPLETE,
            "answers": given,
            "observed": observed,
            "observation": observation,
            "confusion_points": points,
            "defects": row.get("defects") if isinstance(row.get("defects"), list) else [],
            "validation_failures": item_failures,
        })
    for item_id in by_id:
        if item_id not in seen:
            failures.append(f"item_not_answered:{item_id}")
    return failures, verdicts


# --------------------------------------------------------------------------- report


def _confusion_points(submitted: dict[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for item in submitted.get("items") or []:
        for row in item.get("confusion_points") or []:
            index = len(points) + 1
            scene = str(row.get("scene") or "").strip() or None
            points.append({
                "confusion_id": f"CP-{index:02d}" + (f"-{scene}" if scene else ""),
                "scene": scene,
                "question": str(row.get("question") or ""),
                "why": str(row.get("why") or ""),
                "status": "OPEN",
                "writer_response": None,
            })
    return points


def _anonymisation(submitted: dict[str, Any]) -> dict[str, Any]:
    for item in submitted.get("items") or []:
        found = (item.get("request_item") or {}).get("anonymisation")
        if isinstance(found, dict) and found:
            return found
    return {}


def report_pending(submitted: dict[str, Any], submitted_path: Path | str, *,
                   blocking: bool = False) -> dict[str, Any]:
    """The report as it stands right after the review: every point still OPEN."""
    points = _confusion_points(submitted)
    anon = _anonymisation(submitted)
    return {
        "schema": REPORT_SCHEMA,
        "tool": TOOL_ID,
        "policy": POLICY_ID,
        "episode": submitted.get("episode"),
        "request_id": submitted.get("request_id"),
        "request_path": submitted.get("request_path"),
        "request_sha256": submitted.get("request_sha256"),
        "submitted_path": str(submitted_path),
        "reviewer": submitted.get("reviewer"),
        "review_method": REVIEW_METHOD_SCRIPT,
        "reviewed_at": submitted.get("reviewed_at"),
        "basis": "SCRIPT_TEXT_ONLY_NOT_AUDIENCE_FEEDBACK",
        "script_verdict": None,
        "note": "A script review never writes PASS.  Routine confusion points are answered by "
                "the writer and never block; only a MAJOR creative disagreement escalates.",
        "narrative_sha256": anon.get("narrative_sha256"),
        "synopsis_sha256": anon.get("synopsis_sha256"),
        "confusion_points": points,
        "unanswered": [row["confusion_id"] for row in points],
        "escalations": [],
        "review_state": "COMPLETE" if not points else "INCOMPLETE",
        "blocking": bool(blocking),
    }


def respond(submitted: dict[str, Any], submitted_path: Path | str,
            responses: dict[str, Any], *, responses_sha256: str | None = None,
            blocking: bool = False) -> dict[str, Any]:
    """Apply the writer's responses; the report stays INCOMPLETE until every point is answered."""
    from nalu_qa_common import sha256_file

    failures: list[str] = []
    report = report_pending(submitted, submitted_path, blocking=blocking)
    if responses.get("schema") != RESPONSES_SCHEMA:
        failures.append(f"RESPONSES_SCHEMA_INVALID:{responses.get('schema')!r}")
    declarer = str(responses.get("responder") or "").strip()
    if not declarer:
        failures.append("RESPONDER_MISSING")
    elif declarer == str(submitted.get("reviewer") or ""):
        failures.append(f"WRITER_AND_REVIEWER_MUST_DIFFER:{declarer}")
    declared_sha = str(responses.get("submitted_sha256") or "").strip()
    actual_sha = sha256_file(submitted_path)
    if declared_sha and declared_sha != actual_sha:
        failures.append(f"SUBMITTED_SHA256_MISMATCH:declared={declared_sha}")

    by_id = {row["confusion_id"]: row for row in report["confusion_points"]}
    seen: set[str] = set()
    for index, row in enumerate(responses.get("items") or [], 1):
        if not isinstance(row, dict):
            failures.append(f"RESPONSE_NOT_AN_OBJECT:{index}")
            continue
        confusion = str(row.get("confusion_id") or "").strip()
        if confusion not in by_id:
            failures.append(f"RESPONSE_FOR_UNKNOWN_CONFUSION:{confusion or index}")
            continue
        if confusion in seen:
            failures.append(f"RESPONSE_DUPLICATE:{confusion}")
            continue
        seen.add(confusion)
        disposition = str(row.get("disposition") or "").strip()
        text = str(row.get("response") or "").strip()
        target = by_id[confusion]
        if disposition not in RESPONSE_DISPOSITIONS:
            failures.append(f"RESPONSE_DISPOSITION_INVALID:{confusion}:{disposition!r}")
            continue
        if len(text) < MIN_RESPONSE_CHARS:
            failures.append(f"RESPONSE_TOO_SHORT:{confusion}:{len(text)}")
            continue
        target.update({"writer_response": text, "disposition": disposition,
                       "response_chars": len(text)})
        if disposition == "DISAGREE_ESCALATED":
            escalation = row.get("escalation") if isinstance(row.get("escalation"), dict) else {}
            if str(escalation.get("to") or "") != "LINE_OWNER":
                failures.append(f"ESCALATION_TARGET_INVALID:{confusion}")
                continue
            if not str(escalation.get("reason") or "").strip():
                failures.append(f"ESCALATION_REASON_MISSING:{confusion}")
                continue
            target["status"] = "ESCALATED"
            report["escalations"].append({
                "confusion_id": confusion, "reason": str(escalation.get("reason")),
                "to": "LINE_OWNER", "writer_response": text})
        else:
            target["status"] = disposition

    unanswered = [row["confusion_id"] for row in report["confusion_points"]
                  if row["status"] == "OPEN"]
    if unanswered or failures:
        state = "INCOMPLETE"
    elif report["escalations"]:
        state = "COMPLETE_WITH_ESCALATION"
    else:
        state = "COMPLETE"
    report.update({
        "responder": declarer or None,
        "responded_at": responses.get("responded_at"),
        "responses_path": responses.get("_written_to"),
        "responses_sha256": responses_sha256,
        "validation": {"status": "PASS" if not failures else "FAIL", "failures": failures},
        "unanswered": unanswered,
        "review_state": state,
    })
    return report


def materialise(episode: str, submitted: dict[str, Any], submitted_path: Path) -> dict[str, Any]:
    """Called by ``vlm_review_protocol.materialise_kind``.  Writes the pending report only."""
    from nalu_qa_common import write_json

    report = report_pending(submitted, submitted_path)
    path = Path(submitted_path).with_name(Path(submitted_path).name.replace(
        "_submitted.json", "_script_review_report.json"))
    write_json(path, report)
    return {"status": "SCRIPT_REVIEW_PENDING_WRITER_RESPONSE",
            "report": str(path), "confusion_points": len(report["confusion_points"])}


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("synopsis", help="print the anonymised synopsis (writes nothing)")
    show.add_argument("--narrative", type=Path, required=True)

    req = sub.add_parser("request", help="write the script-review request through the protocol")
    req.add_argument("--episode", required=True)
    req.add_argument("--narrative", type=Path)
    req.add_argument("--out", type=Path)

    ans = sub.add_parser("submit", help="validate answers and write the pending report")
    ans.add_argument("--request", type=Path, required=True)
    ans.add_argument("--answers", type=Path, required=True)
    ans.add_argument("--out", type=Path)

    res = sub.add_parser("respond", help="apply the writer's responses to a submitted review")
    res.add_argument("--submitted", type=Path, required=True)
    res.add_argument("--responses", type=Path, required=True)
    res.add_argument("--out", type=Path)
    res.add_argument("--blocking", action="store_true",
                     help="mark the report blocking (off by default; line owner switch)")

    args = parser.parse_args(argv)
    if args.command == "synopsis":
        print(anonymise(args.narrative.read_text(encoding="utf-8"))["synopsis"])
        return 0

    if args.command == "request":
        import vlm_review_protocol as vrp
        payload = vrp.build_request(KIND, args.episode, narrative=args.narrative, out=args.out)
        print(json.dumps({"status": "REQUEST_WRITTEN", "request": payload["_written_to"],
                          "synopsis_sha256": payload["items"][0]["media"][0]["sha256"]},
                         ensure_ascii=False))
        return 0

    if args.command == "submit":
        from nalu_qa_common import read_json, sha256_file, write_json
        from nalu_qa_common import SCHEMA_REQUEST, SCHEMA_SUBMITTED, now

        request = read_json(args.request)
        if not isinstance(request, dict) or request.get("schema") != SCHEMA_REQUEST \
                or request.get("kind") != KIND:
            raise SystemExit(f"not a {SCHEMA_REQUEST} for kind={KIND}: {args.request}")
        answers = read_json(args.answers)
        if not isinstance(answers, dict):
            raise SystemExit(f"unreadable answers: {args.answers}")
        request_sha = sha256_file(args.request)
        failures, verdicts = validate(request, request_sha, answers)
        out = Path(args.out) if args.out else Path(args.request).with_name(
            re.sub(r"_request\.json$", "_submitted.json", Path(args.request).name, flags=re.IGNORECASE))
        if out.resolve() == Path(args.request).resolve():
            # never overwrite the request the review was bound to (lab 化神 E04: an upper-case
            # *_REQUEST.json name was not rewritten and the submission replaced the request)
            out = Path(args.request).with_name(Path(args.request).stem + "_submitted.json")
        record = {
            "schema": SCHEMA_SUBMITTED,
            "request_id": request.get("request_id"),
            "kind": KIND,
            "episode": request.get("episode"),
            "reviewer": answers.get("reviewer"),
            "review_method": REVIEW_METHOD_SCRIPT,
            "reviewed_at": answers.get("reviewed_at"),
            "submitted_at": now(),
            "submitted_by": TOOL_ID,
            "request_path": str(args.request),
            "request_sha256": request_sha,
            "answers_path": str(args.answers),
            "answers_sha256": sha256_file(args.answers),
            "questionnaire": request.get("questionnaire"),
            "validation": {"status": "PASS" if not failures else "FAIL",
                           "failure_count": len(failures), "failures": failures},
            "items": verdicts,
            "verdict_counts": {},
            "materialisation": None,
        }
        by_id = {row["item_id"]: row for row in request.get("items") or []}
        for row in record["items"]:
            row["request_item"] = by_id[row["item_id"]]
        counts: dict[str, int] = {}
        for row in verdicts:
            counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        record["verdict_counts"] = counts
        if failures:
            write_json(out, record)
            print(json.dumps({"status": "INVALID", "failures": failures}, ensure_ascii=False))
            return 2
        record["materialisation"] = materialise(request.get("episode"), record, out)
        write_json(out, record)
        print(json.dumps({"status": "SUBMITTED",
                          "confusion_points": record["materialisation"].get("confusion_points"),
                          "report": record["materialisation"]["report"]}, ensure_ascii=False))
        return 0

    from nalu_qa_common import read_json, sha256_file, write_json
    submitted = read_json(args.submitted)
    responses = read_json(args.responses)
    if not isinstance(submitted, dict) or not isinstance(responses, dict):
        raise SystemExit("SCRIPT_REVIEW_INPUT_UNREADABLE")
    report = respond(submitted, args.submitted, responses,
                     responses_sha256=sha256_file(args.responses), blocking=args.blocking)
    out = Path(args.out) if args.out else Path(args.submitted).with_name(
        Path(args.submitted).name.replace("_submitted.json", "_script_review_report.json"))
    write_json(out, report)
    print(json.dumps({"review_state": report["review_state"],
                      "unanswered": report["unanswered"],
                      "escalations": [row["confusion_id"] for row in report["escalations"]],
                      "report": str(out)}, ensure_ascii=False))
    if report["blocking"] and report["review_state"] == "INCOMPLETE":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
