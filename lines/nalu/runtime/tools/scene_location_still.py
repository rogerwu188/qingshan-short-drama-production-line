#!/usr/bin/env python3
"""SCENE_LOCATION_STILL_V1 -- one people-free location still per scene place, made in S5 (owner-approved small cost).

Device 1101 E24 (2026-11-23): every unit of a teahouse / rouge-shop / boat episode rendered the series' standing
"mountain gate and spirit fields"; VU-004 jumped from the teahouse interior to the field inside one clip.  H3 had no
picture of the scene's place beside the opening frame: the NALU line never produces the stage-3(a) location plate
(``asset_library.assets.scenes`` stays empty, the keyframes draw on the topology render), so
``scene_location_lock.location_reference_for_unit`` only ever found a same-scene keyframe -- and none at all for a
unit whose cast differs from the scene's other shots.

This module closes that gap with the existing image path (tools/hopsapi_image_client, the durable transaction store
the budget ledger reads):

* ``plan``   (free)  one row per scene LOCATION that has neither a LOCKED stage-3(a) plate nor a READY still: the
                     source is the scene's Q1-admitted keyframe showing the fewest people (earliest first);
* ``generate`` (paid, run by S5 through ``Ctx.paid_step`` after Q1 + start-frame evidence) one image-to-image
                     request per row: "this exact place with every person removed".  Durable intent before the POST,
                     never resent after a lost response, at most ``MAX_ATTEMPTS`` creates per location (the first + the
                     existing one-redo rule for an uncharged failure).  The still is normalised to 9:16 and registered
                     in ``<runtime>/preproduction/<EP>/scene_location_stills/scene_location_stills.json`` (sha-bound).

``registered_still`` is what the H3 compile (build_nalu_preproduction._locked_scene_plate) reads: the LOCKED plate
wins, else the READY still, else the scene keyframe fallback.  Cost: gpt-image-2 at the per-image planning rate
(~1.2 credits) per location -- one to three per episode.  Never blocks S5: any failure leaves the unit on the
keyframe fallback exactly as before.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_location_lock as _sll  # noqa: E402

SCHEMA = "nalu.scene_location_stills.v1"
POLICY = "SCENE_LOCATION_STILL_V1"
DIRNAME = "scene_location_stills"
REGISTRY_NAME = "scene_location_stills.json"
IMAGE_STORE_DIRNAME = "giggle_submit_transactions"  # the store nalu_budget_ledger reads (provider_cost_credits)
TASK_PREFIX = "scene_location_still"
MAX_ATTEMPTS = 2
DEFAULT_WAIT_SECONDS = 300.0
POLL_SECONDS = 6.0
READY = "READY"
ROLE = "SCENE_LOCATION_STILL"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def stills_dir(runtime_root: Path | str, episode: str) -> Path:
    return Path(runtime_root) / "preproduction" / episode / DIRNAME


def registry_path(runtime_root: Path | str, episode: str) -> Path:
    return stills_dir(runtime_root, episode) / REGISTRY_NAME


def safe_key(location_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(location_id)).strip("-") or "LOC"


def registered_still(location_id: str, *, episode: str, runtime_root: Path | str) -> Path | None:
    """The READY still of ``location_id`` whose bytes still match the registry sha; None otherwise."""
    row = ((read_json(registry_path(runtime_root, episode), {}) or {}).get("locations") or {}).get(str(location_id))
    if not isinstance(row, dict) or row.get("status") != READY:
        return None
    path = Path(str(row.get("path") or ""))
    if path.is_file() and row.get("sha256") and sha256_file(path) == row["sha256"]:
        return path
    return None


def _locked_plate(library: dict[str, Any], location_id: str) -> bool:
    scenes = ((library or {}).get("assets") or {}).get("scenes") or {}
    row = scenes.get(location_id) or next(
        (r for r in scenes.values() if isinstance(r, dict)
         and location_id in {str(r.get(k) or "") for k in ("location_id", "contract_asset_id", "entity_id")}), {})
    if not isinstance(row, dict) or row.get("status") != "LOCKED" or (row.get("qa") or {}).get("status") != "PASS":
        return False
    return any(isinstance(a, dict) and Path(str(a.get("path") or "")).is_file() for a in row.get("artifacts") or [])


def plan(editorial: dict[str, Any], keyframe_dir: Path, *, episode: str, runtime_root: Path | str,
         library: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Locations that need a still, with their source keyframe.  Pure apart from reading files.  A location with a
    LOCKED plate or a READY still, or whose scenes have no keyframe on disk yet, gets no row."""
    by_location: dict[str, dict[str, Any]] = {}
    for index, shot in enumerate(editorial.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        location = str(((spec.get("space") or {}) if isinstance(spec.get("space"), dict) else {}).get("location") or "")
        if not location or location.upper() in {"UNKNOWN_LOCATION", "UNSPECIFIED"}:
            continue
        frame = _sll._latest_keyframe(Path(keyframe_dir), str(shot.get("shot_id") or ""))
        row = by_location.setdefault(location, {"location_id": location, "scene_ids": [], "candidates": []})
        scene = str(shot.get("scene_id") or "")
        if scene and scene not in row["scene_ids"]:
            row["scene_ids"].append(scene)
        if frame is not None:
            row["candidates"].append((len(_sll._visible_ids(spec)), index, str(shot.get("shot_id")), frame, spec))
    out = []
    for location, row in by_location.items():
        if _locked_plate(library or {}, location) or registered_still(location, episode=episode,
                                                                       runtime_root=runtime_root):
            continue
        if not row["candidates"]:
            continue
        people, _, shot_id, frame, spec = sorted(row["candidates"], key=lambda c: (c[0], c[1]))[0]
        out.append({"location_id": location, "scene_ids": row["scene_ids"], "source_shot_id": shot_id,
                    "source_keyframe": str(frame), "source_keyframe_sha256": sha256_file(frame),
                    "people_in_source": people, "location_words": _location_words(spec)})
    return out


def _location_words(spec: dict[str, Any]) -> str:
    try:
        engine = Path(os.environ.get("QINGSHAN_ENGINE_ROOT") or Path(__file__).resolve().parents[4])
        if str(engine) not in sys.path:
            sys.path.insert(0, str(engine))
        from tools.h3_director_prompt_v2 import scene_location_words  # noqa: PLC0415
        words = scene_location_words({"ordered_prompt_specs": [spec]})
    except Exception:  # noqa: BLE001
        words = ""
    return "" if any("㐀" <= ch <= "鿿" for ch in words) else words


def still_prompt(row: dict[str, Any]) -> str:
    place = f" The place is the {row['location_words']}." if row.get("location_words") else ""
    return ("Edit this image: show exactly the same place -- the same architecture, furniture, set dressing, materials, "
            "light, time of day and camera position -- with every person removed, as an empty location plate." + place
            + " No people, no figures, no hands or body parts, no reflections of people, no text, letters, captions or "
            "logos. Keep the period of the place exactly as shown; add no modern object. Keep the image's own visual "
            "style and light.")


def _attempt_finished(tx: dict[str, Any]) -> str | None:
    """FAILED_UNCHARGED (a redo may follow), LOST (never resend) or None (bound / in progress)."""
    state = str(tx.get("state") or "")
    if state == "NOT_CHARGED_RETRYABLE":
        return "FAILED_UNCHARGED"
    if state == "SUBMITTED_TASK_ID_BOUND":
        remote = str(tx.get("remote_terminal_state") or tx.get("provider_remote_status") or "").lower()
        if remote in ("failed", "cancelled") and not tx.get("provider_cost_credits"):
            return "FAILED_UNCHARGED"
        return None
    return "LOST"


def _poll(client: Any, tx_path: Path, out_path: Path, *, wait_seconds: float,
          sleep: Callable[[float], None], clock: Callable[[], float]) -> dict[str, Any]:
    tx = read_json(tx_path, {}) or {}
    task_id = str(tx.get("task_id") or "")
    deadline = clock() + max(0.0, wait_seconds)
    while True:
        try:
            status = client.query_task(task_id)
        except Exception as exc:  # noqa: BLE001 -- a GET; the next S5 run polls again
            return {"status": "PENDING", "task_id": task_id, "error": type(exc).__name__}
        remote = str(status.get("remote_status") or "unknown")
        if remote == "completed" and status.get("urls"):
            client.record_settlement(tx_path, task_id, status, now=utc_now())
            try:
                landed = client.download_image(status["urls"][0], out_path)
            except Exception as exc:  # noqa: BLE001 -- paid: retry the download next run
                return {"status": "DOWNLOAD_PENDING", "task_id": task_id, "error": str(exc)[:200]}
            try:
                client.normalise_portrait_9_16(out_path)
            except Exception:  # noqa: BLE001 -- a non-9:16 still is still a usable background reference
                pass
            tx = read_json(tx_path, {}) or {}
            return {"status": READY, "task_id": task_id, "sha256": sha256_file(out_path),
                    "cost_credits": tx.get("provider_cost_credits"), "landed": landed}
        if remote in ("failed", "cancelled"):
            client.record_settlement(tx_path, task_id, status, now=utc_now())
            return {"status": "TASK_FAILED", "task_id": task_id, "error": str(status.get("error") or "")[:200]}
        if clock() >= deadline:
            return {"status": "PENDING", "task_id": task_id, "remote_status": remote}
        sleep(POLL_SECONDS)


def generate_one(row: dict[str, Any], registry: dict[str, Any], *, client: Any, engine_root: Path,
                 out_dir: Path, episode: str, wait_seconds: float = DEFAULT_WAIT_SECONDS,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 save: Callable[[], None] = lambda: None, prompt: str | None = None, task_key: str | None = None,
                 out_path: Path | None = None, intent_extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resume / submit / poll one location.  ``registry`` is mutated (the caller persists it via ``save``).

    ``prompt`` / ``task_key`` / ``out_path`` / ``intent_extra`` let another single-image Img2Img job reuse the same
    durable path (burn_clean_start_frame.py, 2026-11-27); omitted, everything is exactly the location still."""
    location = row["location_id"]
    entry = registry.setdefault("locations", {}).setdefault(location, {"attempts": []})
    entry.update({k: row[k] for k in ("scene_ids", "source_shot_id", "source_keyframe", "source_keyframe_sha256")})
    out_path = Path(out_path) if out_path is not None else out_dir / f"{episode}_{safe_key(location)}_LOCATION_STILL.png"
    attempts = entry["attempts"]
    if attempts:
        tx_path = Path(attempts[-1]["transaction"])
        finished = _attempt_finished(read_json(tx_path, {}) or {})
        if finished is None:
            result = _poll(client, tx_path, out_path, wait_seconds=wait_seconds, sleep=sleep, clock=clock)
            if result["status"] != "TASK_FAILED":
                if result["status"] == READY:
                    entry.update({"status": READY, "path": str(out_path), "sha256": result["sha256"],
                                  "cost_credits": result.get("cost_credits"), "ready_at": utc_now()})
                else:
                    entry["status"] = "SUBMITTED"
                save()
                return {"location_id": location, **result}
            finished = "FAILED_UNCHARGED"
        attempts[-1]["outcome"] = finished
        if finished == "LOST":
            entry["status"] = "RESPONSE_LOST"
            save()
            return {"location_id": location, "status": "RESPONSE_LOST",
                    "note": "no idempotency key: never resent; reconcile on the HopsAPI console"}
        if len(attempts) >= MAX_ATTEMPTS:
            entry["status"] = "FAILED"
            save()
            return {"location_id": location, "status": "FAILED", "attempts": len(attempts)}
    attempt_no = len(attempts) + 1
    prompt = prompt or still_prompt(row)
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    task_key = task_key or f"{TASK_PREFIX}__{safe_key(location)}"
    try:
        prepared = client.prepare_request(prompt=prompt, reference_paths=[row["source_keyframe"]], aspect_ratio="9:16",
                                          task_key=task_key)
    except Exception as exc:  # noqa: BLE001 -- pre-intent: nothing POSTed, nothing charged
        return {"location_id": location, "status": "PREPARE_FAILED", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    fingerprint = hashlib.sha256(json.dumps({"task": task_key, "prompt_sha256": prompt_sha, "attempt": attempt_no,
                                             "reference_sha256": [row["source_keyframe_sha256"]],
                                             "model": client.MODEL, "resolution": prepared["resolution"]},
                                            sort_keys=True).encode("utf-8")).hexdigest()
    tx_path = Path(engine_root) / "workflow" / "tasks" / IMAGE_STORE_DIRNAME / episode / f"{task_key}__{fingerprint[:16]}.json"
    intent = {
        "schema": "qingshan.giggle_submit_transaction.v1", "episode": episode, "task_key": task_key,
        "attempt_id": str(uuid.uuid4()), "submission_fingerprint": fingerprint, "state": "INTENT_RECORDED",
        "intent_recorded_at": utc_now(), "model": getattr(client, "LOGICAL_MODEL", client.MODEL),
        "prompt_sha256": prompt_sha, "reference_image_sha256s": [row["source_keyframe_sha256"]],
        "endpoint": "hopsapi:/router/task/create", "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
        **({"scene_location_still": True, "location_id": location} if intent_extra is None else dict(intent_extra)),
        "still_attempt": attempt_no, **client.intent_fields(prepared),
    }
    atomic_json(tx_path, intent)
    attempts.append({"attempt": attempt_no, "transaction": str(tx_path), "intent_recorded_at": intent["intent_recorded_at"]})
    entry.update({"status": "SUBMITTING", "prompt": prompt, "prompt_sha256": prompt_sha})
    save()  # durable before the POST
    previous = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
    try:
        response = client.create_image_task(prepared["payload"])
    except client.hops.HopsapiNotCharged as exc:
        intent.update({"state": "NOT_CHARGED_RETRYABLE", "credit_status": "NOT_CHARGED_RETRYABLE",
                       "response_received_at": utc_now(), "error": str(exc)[:500],
                       "retry_guard": "RETRY_ALLOWED_NEW_ATTEMPT"})
        atomic_json(tx_path, intent)
        attempts[-1]["outcome"] = "FAILED_UNCHARGED"
        entry["status"] = "SUBMIT_DECLINED"
        save()
        return {"location_id": location, "status": "SUBMIT_DECLINED", "error": str(exc)[:200]}
    except (Exception, SystemExit) as exc:  # noqa: BLE001 -- may have been charged: never resend
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": str(exc)[:500],
                       "response_lost_at": utc_now(),
                       "operator_note": "HopsAPI has no idempotency key: check the console before any new POST"})
        atomic_json(tx_path, intent)
        attempts[-1]["outcome"] = "LOST"
        entry["status"] = "RESPONSE_LOST"
        save()
        return {"location_id": location, "status": "RESPONSE_LOST", "transaction": str(tx_path)}
    finally:
        if previous is None:
            os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
        else:
            os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = previous
    intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": str(response["task_id"]),
                   "provider_response": response, "response_recorded_at": utc_now()})
    atomic_json(tx_path, intent)
    entry["status"] = "SUBMITTED"
    save()
    result = _poll(client, tx_path, out_path, wait_seconds=wait_seconds, sleep=sleep, clock=clock)
    if result["status"] == READY:
        entry.update({"status": READY, "path": str(out_path), "sha256": result["sha256"],
                      "cost_credits": result.get("cost_credits"), "ready_at": utc_now()})
        save()
    return {"location_id": location, **result}


def _image_client(engine_root: Path):
    if str(engine_root) not in sys.path:
        sys.path.insert(0, str(engine_root))
    from tools import hopsapi_image_client  # noqa: PLC0415
    return hopsapi_image_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("plan", "generate"))
    parser.add_argument("--episode", required=True)
    parser.add_argument("--editorial", required=True)
    parser.add_argument("--keyframe-dir", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--asset-library", default="")
    parser.add_argument("--max", type=int, default=3, help="at most this many new stills per run")
    parser.add_argument("--wait-seconds", type=float, default=DEFAULT_WAIT_SECONDS)
    args = parser.parse_args(argv)
    editorial = read_json(Path(args.editorial), {}) or {}
    library = read_json(Path(args.asset_library), {}) if args.asset_library else {}
    reg_path = registry_path(args.runtime_root, args.episode)
    registry = read_json(reg_path, {}) or {"schema": SCHEMA, "policy": POLICY, "episode": args.episode, "locations": {}}
    pending = [loc for loc, row in (registry.get("locations") or {}).items()
               if isinstance(row, dict) and row.get("status") in {"SUBMITTING", "SUBMITTED"}]
    rows = plan(editorial, Path(args.keyframe_dir), episode=args.episode, runtime_root=args.runtime_root,
                library=library)
    rows = [r for r in rows if r["location_id"] not in pending][:max(0, args.max)] + \
        [r for r in rows if r["location_id"] in pending]
    if args.command == "plan":
        print(json.dumps({"schema": SCHEMA, "status": "PLANNED", "episode": args.episode, "rows": rows,
                          "images": len(rows)}, ensure_ascii=False))  # one line: Ctx.qa_json reads the tail
        return 0
    engine = Path(args.engine_root)
    client = _image_client(engine)
    provider = client.resolve_image_provider().get("provider")
    if provider != client.PROVIDER_HOPSAPI:
        print(json.dumps({"schema": SCHEMA, "status": "SKIPPED_PROVIDER_NOT_HOPSAPI", "provider": provider}))
        return 0
    out_dir = stills_dir(args.runtime_root, args.episode)
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [generate_one(row, registry, client=client, engine_root=engine, out_dir=out_dir, episode=args.episode,
                            wait_seconds=args.wait_seconds, save=lambda: atomic_json(reg_path, registry))
               for row in rows]
    registry["updated_at"] = utc_now()
    atomic_json(reg_path, registry)
    print(json.dumps({"schema": SCHEMA, "status": "DONE", "episode": args.episode,
                      "results": [{k: r.get(k) for k in ("location_id", "status", "task_id", "cost_credits", "error")}
                                  for r in results], "registry": str(reg_path)}, ensure_ascii=False))
    # a lost create response may have been charged: a non-zero exit keeps the S5 budget reservation held
    return 3 if any(r.get("status") == "RESPONSE_LOST" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
