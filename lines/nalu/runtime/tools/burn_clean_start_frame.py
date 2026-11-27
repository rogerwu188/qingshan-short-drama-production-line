#!/usr/bin/env python3
"""BURN_ESCALATION_CLEAN_FRAME_V1 -- one clean first frame for a unit still burned after the final-fix retries.

Device 1101 E29 (2026-11-27): VU-013 burned the line again after the final-fix redo and its two retries (each one
opening on a perturbed copy of the same start frame) and the one unit held the whole episode
(RELEASE_HELD:BURN_UNRESOLVED).  The lab's burn bisect (2026-11-26, ~/nalu_lab/perf_lab/BURN_BISECT2.md) found the
burn driven by the INPUTS: an @Image1 that never came from burned / subtitled footage (a gpt-image-2 Img2Img
re-render) gave 0 burned renders on all three lines where every wording burned.

``generate`` (paid, run by S6 through ``Ctx.paid_step``) sends ONE Img2Img request per unit: "re-render this exact
frame, nothing written anywhere" (final_fix_round.CLEAN_FRAME_PROMPT) on the unit's start frame, through the same
durable path as the scene location stills (scene_location_still.generate_one: intent before the POST, never resent
after a lost response, at most two creates for an uncharged failure), normalised to 9:16.  The landed image is read
by the S6 burned-text detector's OCR (tail_frame_text_clean.find_text_boxes, our subtitle band): a frame with text
in it is ``TEXT_IN_CLEAN_FRAME`` and is not used.  Registry:
``<preproduction>/burn_clean_start_frames/<EP>_CLEAN_START_FRAMES.json``.  ~1.4 credits (gpt-image-2 planning rate).

The video submitter sends the frame as @Image1 of the escalation take (``h3_final_fix.clean_start_frame``); the
compiled task, its references and their Q1 admission are unchanged (the same send-time substitution as the burn-retry
perturbation).  Never blocks: any failure leaves the unit on its best take, exactly as before.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_location_still as _sls  # noqa: E402

SCHEMA = "nalu.burn_clean_start_frames.v1"
POLICY = "BURN_ESCALATION_CLEAN_FRAME_V1"
DIRNAME = "burn_clean_start_frames"
TASK_PREFIX = "burn_clean_start_frame"
READY = _sls.READY


def registry_path(out_dir: Path | str, episode: str) -> Path:
    return Path(out_dir) / f"{episode}_CLEAN_START_FRAMES.json"


def frame_path(out_dir: Path | str, episode: str, unit_id: str) -> Path:
    return Path(out_dir) / f"{episode}_{_sls.safe_key(unit_id)}_CLEAN_START_FRAME.png"


def prompt_text() -> str:
    try:
        import final_fix_round as _ffr  # noqa: PLC0415 -- same directory
        return _ffr.CLEAN_FRAME_PROMPT
    except Exception:  # noqa: BLE001
        return ("Re-render this exact frame as a fresh, clean film still with the same people, place, pose, framing "
                "and light. Nothing is written anywhere in the image: no subtitles, captions, letters or logos.")


def text_check(image: Path, engine_root: Path | None = None) -> dict[str, Any]:
    """OCR of the landed frame (the tail-frame cleaner's caption rule).  FAIL_OPEN when OCR / OpenCV is missing."""
    try:
        import cv2  # noqa: PLC0415
        engine = Path(engine_root) if engine_root else Path(__file__).resolve().parents[4]
        if str(engine / "tools") not in sys.path:
            sys.path.insert(0, str(engine / "tools"))
        import tail_frame_text_clean as _ttc  # noqa: PLC0415
        frame = cv2.imread(str(image))
        if frame is None:
            return {"status": "FAIL_OPEN", "error": "UNREADABLE_IMAGE"}
        boxes = _ttc.find_text_boxes(frame, _ttc._default_ocr)
        return {"status": "TEXT" if boxes else "CLEAN", "boxes": len(boxes),
                "texts": [str(b.get("text") or "") for b in boxes][:6]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL_OPEN", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def generate(*, episode: str, unit_id: str, source: Path, out_dir: Path, engine_root: Path, client: Any,
             wait_seconds: float = _sls.DEFAULT_WAIT_SECONDS, checker=text_check) -> dict[str, Any]:
    """Resume / submit / poll the unit's clean frame; returns {unit_id, status, path?, sha256?, cost_credits?}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    reg_path = registry_path(out_dir, episode)
    registry = _sls.read_json(reg_path, {}) or {"schema": SCHEMA, "policy": POLICY, "episode": episode,
                                                 "locations": {}}
    entry = (registry.get("locations") or {}).get(unit_id) or {}
    if entry.get("status") == READY and entry.get("path") and Path(entry["path"]).is_file() \
            and _sls.sha256_file(Path(entry["path"])) == entry.get("sha256"):
        return {"unit_id": unit_id, "status": READY, "path": entry["path"], "sha256": entry["sha256"],
                "cost_credits": entry.get("cost_credits"), "text_check": entry.get("text_check"), "reused": True}
    row = {"location_id": unit_id, "scene_ids": [], "source_shot_id": None, "source_keyframe": str(source),
           "source_keyframe_sha256": _sls.sha256_file(source)}
    out = frame_path(out_dir, episode, unit_id)
    result = _sls.generate_one(
        row, registry, client=client, engine_root=engine_root, out_dir=out_dir, episode=episode,
        wait_seconds=wait_seconds, save=lambda: _sls.atomic_json(reg_path, registry), prompt=prompt_text(),
        task_key=f"{TASK_PREFIX}__{_sls.safe_key(unit_id)}", out_path=out,
        intent_extra={"burn_clean_start_frame": True, "unit_id": unit_id, "policy": POLICY})
    result = {"unit_id": unit_id, **{k: v for k, v in result.items() if k != "location_id"}}
    if result.get("status") == READY:
        check = checker(out, engine_root)
        entry = registry["locations"][unit_id]
        entry["text_check"] = check
        if check.get("status") == "TEXT":
            entry["status"] = "TEXT_IN_CLEAN_FRAME"
            result.update(status="TEXT_IN_CLEAN_FRAME")
        result.update(path=str(out), text_check=check)
        _sls.atomic_json(reg_path, registry)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("plan", "generate"))
    parser.add_argument("--episode", required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--wait-seconds", type=float, default=_sls.DEFAULT_WAIT_SECONDS)
    args = parser.parse_args(argv)
    source = Path(args.source)
    if not source.is_file():
        print(json.dumps({"schema": SCHEMA, "status": "NO_SOURCE_FRAME", "unit_id": args.unit}))
        return 0
    if args.command == "plan":
        print(json.dumps({"schema": SCHEMA, "status": "PLANNED", "unit_id": args.unit, "images": 1,
                          "source": str(source)}))
        return 0
    engine = Path(args.engine_root)
    client = _sls._image_client(engine)
    provider = client.resolve_image_provider().get("provider")
    if provider != client.PROVIDER_HOPSAPI:
        print(json.dumps({"schema": SCHEMA, "status": "SKIPPED_PROVIDER_NOT_HOPSAPI", "provider": provider}))
        return 0
    result = generate(episode=args.episode, unit_id=args.unit, source=source, out_dir=Path(args.out_dir),
                      engine_root=engine, client=client, wait_seconds=args.wait_seconds)
    print(json.dumps({"schema": SCHEMA, **result}, ensure_ascii=False))  # one line: Ctx.qa_json reads the tail
    # a lost create response may have been charged: a non-zero exit keeps the S6 budget reservation held
    return 3 if result.get("status") == "RESPONSE_LOST" else 0


if __name__ == "__main__":
    raise SystemExit(main())
