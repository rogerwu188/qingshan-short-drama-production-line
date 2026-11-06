#!/usr/bin/env python3
"""Poll and download a submitted image batch without resubmission (Giggle or HopsAPI task ids).

HopsAPI rows (``provider: hopsapi`` / ``tsk_`` ids, owner 2026-10-30) are queried through
tools/hopsapi_image_client.py, downloaded + verified to the SAME file name the Giggle harvest uses
(``<EP>_<task key>_<task id>.png``), and their settled ``cost`` is written onto the durable
transaction (``provider_cost_credits``) for nalu_budget_ledger.py."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.request import Request, urlopen

try:
    from giggle_api_client import query_task
    from submit_giggle_task_manifest import ensure_giggle_api_key
    import hopsapi_image_client as image_client
except ModuleNotFoundError:  # Imported as tools.harvest_giggle_image_batch.
    from tools.giggle_api_client import query_task
    from tools.submit_giggle_task_manifest import ensure_giggle_api_key
    from tools import hopsapi_image_client as image_client


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"completed", "failed", "error", "cancelled", "timeout", "completed_without_url"}
CREDIT_KEYS = {
    "credit", "credits", "credit_cost", "credits_cost", "consumed_credit",
    "consumed_credits", "credit_used", "credits_used", "used_credit",
    "used_credits", "point_cost", "points_cost", "consumed_points",
}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "task"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def explicit_credit(payload: Any) -> int | float | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in CREDIT_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
        for value in payload.values():
            found = explicit_credit(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = explicit_credit(value)
            if found is not None:
                return found
    return None


def batch_credit_assignment(source: dict[str, Any], result_count: int) -> tuple[int | float | None, dict[str, Any] | None]:
    """Return per-item credit only for an exact, uniform isolated batch ledger."""
    reconciliation = source.get("credit_reconciliation")
    if not isinstance(reconciliation, dict) or reconciliation.get("status") not in {"PASS", "PASS_BOUNDED"}:
        return None, reconciliation if isinstance(reconciliation, dict) else None
    rows = reconciliation.get("statement_rows") or []
    if reconciliation.get("matched_count") != result_count or len(rows) != result_count or result_count < 1:
        return None, reconciliation
    values: list[float] = []
    for row in rows:
        try:
            values.append(abs(float(row["credit"])))
        except (KeyError, TypeError, ValueError):
            return None, reconciliation
    if len(set(values)) != 1:
        return None, reconciliation
    value = values[0]
    return int(value) if value.is_integer() else value, reconciliation


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "qingshan-image-batch-harvester/1.0"})
    with urlopen(request, timeout=240) as response, partial.open("wb") as target:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
    os.replace(partial, destination)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def harvest_workers(default: int = 6) -> int:
    """How many task queries/downloads run at once inside one poll tick.

    One image batch is commonly ~50 tasks and the watch loop polls every 15 s;
    each task is one HTTP GET plus one download, both of which release the GIL.
    The bound is a poll-tick bound, not provider capacity; NALU_HARVEST_WORKERS
    overrides it.
    """
    try:
        return max(1, int(os.environ.get("NALU_HARVEST_WORKERS") or default))
    except ValueError:
        return default


def row_provider(row: dict[str, Any]) -> str:
    recorded = str(row.get("provider") or "").lower()
    if recorded in image_client.PROVIDERS:
        return recorded
    return (image_client.PROVIDER_HOPSAPI if image_client.is_hopsapi_task_id(row.get("task_id"))
            else image_client.PROVIDER_GIGGLE)


def harvest_one_hopsapi(row: dict[str, Any], episode: str, output_dir: Path, raw_dir: Path,
                        studio_project_id: str | None = None) -> dict[str, Any]:
    """GET the HopsAPI task (free), download + verify a completed image, record the settlement."""
    task_id = str(row["task_id"])
    status = image_client.query_task(task_id)
    raw_path = raw_dir / f"{safe(row['task_key'])}_{task_id}.json"
    atomic_json(raw_path, {"provider": image_client.PROVIDER_HOPSAPI, **status})
    remote = str(status.get("remote_status") or "unknown")
    item: dict[str, Any] = {**row, "provider": image_client.PROVIDER_HOPSAPI, "remote_status": remote,
                            "raw_response": str(raw_path)}
    if remote == "completed" and status.get("urls"):
        output = output_dir / f"{episode}_{safe(row['task_key'])}_{task_id}.png"
        if not output.is_file():
            image_client.download_image(str(status["urls"][0]), output)
        digest = sha256(output)
        item.update({"output_path": str(output), "sha256": digest, "bytes": output.stat().st_size})
        archived = studio_archive(output, episode, row, raw_path, studio_project_id, digest)
        if archived is not None:
            item["studio_archive"] = archived
    elif remote == "completed":
        item["remote_status"] = remote = "completed_without_url"
    cost = status.get("cost")
    if remote in image_client.hops.TERMINAL_FAILED:
        item.update({"credit": 0, "credit_status": "FAILED_ZERO", "provider_error": status.get("error")})
        if image_client.is_provider_error_failure(status):
            # upstream gpt-image-2 refusal (424, uncharged), not a defect of this request
            item["failure_class"] = "HOPSAPI_PROVIDER_ERROR_424"
    elif remote == "completed" and isinstance(cost, (int, float)):
        item.update({"credit": cost, "credit_status": "EXPLICIT_HOPSAPI_COST"})
    else:
        item.update({"credit": None, "credit_status": "UNKNOWN_API_FIELD_MISSING" if remote.startswith("completed")
                     else "PENDING"})
    if row.get("transaction") and (remote in image_client.hops.TERMINAL_FAILED or "output_path" in item):
        settled = image_client.record_settlement(resolve(row["transaction"]), task_id, status,
                                                 now=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        item["settlement_recorded"] = bool(settled)
    return item


def studio_archive(output: Path, episode: str, row: dict[str, Any], raw_path: Path,
                   project_id: str | None, digest: str) -> dict[str, Any] | None:
    """Archive the downloaded ORIGINAL into the studio asset library (UNREVIEWED until a lock).

    Only for reference-image harvests that name their project (S3 passes --studio-archive-project);
    keyframe harvests do not, so they are not studio assets.  Never raises: the image is already on
    disk and ``studio_asset_library.py migrate --harvest-status`` sweeps anything missed.
    """
    if not project_id:
        return None
    try:
        try:
            from tools import studio_asset_library as studio  # noqa: PLC0415
        except ModuleNotFoundError:  # pragma: no cover - flat tools/ on sys.path
            import studio_asset_library as studio  # type: ignore[no-redef]
        return studio.archive_harvested_image(output, episode=episode, row={**row, "sha256": digest},
                                              project_id=project_id, raw_response=raw_path)
    except Exception as exc:  # noqa: BLE001 - archiving must never break a harvest that already has the image
        return {"status": "ARCHIVE_NOT_RUN", "error": f"{type(exc).__name__}:{exc}"}


def harvest_one(
    row: dict[str, Any],
    episode: str,
    output_dir: Path,
    raw_dir: Path,
    batch_credit: int | float | None,
    studio_project_id: str | None = None,
) -> dict[str, Any]:
    """Query one submitted image task and download its plate when complete.

    Writes only files keyed by this row (raw response by task key + id, plate by
    episode + task key + id), so rows are independent.  ``batch_credit`` is read
    once by the caller and passed in unchanged.
    """
    if row_provider(row) == image_client.PROVIDER_HOPSAPI:
        return harvest_one_hopsapi(row, episode, output_dir, raw_dir, studio_project_id)
    task_id = row["task_id"]
    response = query_task(SimpleNamespace(task_id=task_id))
    raw_path = raw_dir / f"{safe(row['task_key'])}_{task_id}.json"
    atomic_json(raw_path, response)
    data = response.get("data") or {}
    status = str(data.get("status") or "unknown").lower()
    explicit = explicit_credit(response)
    credit = explicit if explicit is not None else batch_credit if status == "completed" else None
    item: dict[str, Any] = {
        **row,
        "remote_status": status,
        "credit": 0 if status in {"failed", "error", "cancelled", "timeout"} else credit,
        "credit_status": (
            "FAILED_ZERO" if status in {"failed", "error", "cancelled", "timeout"}
            else "EXPLICIT" if explicit is not None
            else "KNOWN_BATCH_LEDGER_EXACT_COUNT" if credit is not None
            else "UNKNOWN_API_FIELD_MISSING" if status == "completed"
            else "PENDING"
        ),
        "raw_response": str(raw_path),
    }
    urls = data.get("urls") or []
    if status == "completed" and urls:
        output = output_dir / f"{episode}_{safe(row['task_key'])}_{task_id}.png"
        if not output.is_file():
            download(str(urls[0]), output)
        digest = sha256(output)
        item.update({"output_path": str(output), "sha256": digest, "bytes": output.stat().st_size})
        archived = studio_archive(output, episode, row, raw_path, studio_project_id, digest)
        if archived is not None:
            item["studio_archive"] = archived
    return item


def poll_once(submit_report: Path, output_dir: Path, raw_dir: Path,
              studio_project_id: str | None = None) -> dict[str, Any]:
    source = json.loads(submit_report.read_text(encoding="utf-8"))
    episode = safe(str(source.get("episode") or "EPISODE"))
    rows = source.get("results") or []
    batch_credit, credit_reconciliation = batch_credit_assignment(source, len(rows))
    workers = harvest_workers()
    if workers <= 1 or len(rows) <= 1:
        results = [harvest_one(row, episode, output_dir, raw_dir, batch_credit, studio_project_id) for row in rows]
    else:
        # Query the whole batch concurrently; results stay in submit-report order so
        # the status file and its counts are stable.  Any row's exception fails the
        # tick, exactly as the serial loop did.
        from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

        with ThreadPoolExecutor(max_workers=min(workers, len(rows))) as pool:
            futures = [pool.submit(harvest_one, row, episode, output_dir, raw_dir, batch_credit, studio_project_id)
                       for row in rows]
            results = [future.result() for future in futures]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["remote_status"]] = counts.get(item["remote_status"], 0) + 1
    return {
        "schema": "qingshan.giggle_image_batch_harvest.v1",
        "episode": source.get("episode"),
        "submit_report": str(submit_report),
        "status_counts": counts,
        "all_terminal": bool(results) and all(item["remote_status"] in TERMINAL for item in results),
        "all_completed": bool(results) and all(item["remote_status"] == "completed" for item in results),
        "credit_known_total": sum(item["credit"] for item in results if isinstance(item.get("credit"), (int, float))),
        "credit_unknown_success_count": sum(item["credit_status"] == "UNKNOWN_API_FIELD_MISSING" for item in results),
        "credit_reconciliation": credit_reconciliation,
        "provider_error_424_count": sum(item.get("failure_class") == "HOPSAPI_PROVIDER_ERROR_424" for item in results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit-report", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--status-report", required=True)
    parser.add_argument("--raw-dir", required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--studio-archive-project",
                        help="project id: archive each downloaded original into the studio asset library "
                             "(acts only when the library is enabled; see configs/STUDIO_ASSET_LIBRARY_V1.json)")
    args = parser.parse_args()
    submit_report = resolve(args.submit_report)
    rows = json.loads(submit_report.read_text(encoding="utf-8")).get("results") or []
    providers = {row_provider(row) for row in rows if isinstance(row, dict)}
    if image_client.PROVIDER_GIGGLE in providers or not providers:
        ensure_giggle_api_key()
    if image_client.PROVIDER_HOPSAPI in providers and not os.environ.get(image_client.API_KEY_ENV, "").strip():
        raise SystemExit(f"{image_client.API_KEY_ENV} is not set")
    output_dir = resolve(args.output_dir)
    raw_dir = resolve(args.raw_dir)
    status_report = resolve(args.status_report)
    while True:
        payload = poll_once(submit_report, output_dir, raw_dir, args.studio_archive_project)
        atomic_json(status_report, payload)
        print(json.dumps({"status_counts": payload["status_counts"], "all_terminal": payload["all_terminal"]}, ensure_ascii=False), flush=True)
        if payload["all_terminal"] and payload["provider_error_424_count"]:
            print(f"HOPSAPI_IMAGE_PROVIDER_OUTAGE: {payload['provider_error_424_count']} task(s) settled as the "
                  "uncharged upstream 424 'Provider error' (0 credits) — provider-side, not a reference/prompt "
                  "defect; rerun the same stage after the cooldown (the submitter retires them and re-POSTs)",
                  file=sys.stderr, flush=True)
        if not args.watch or payload["all_terminal"]:
            return 0 if payload["all_completed"] else 2 if payload["all_terminal"] else 0
        time.sleep(max(2, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
