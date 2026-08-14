#!/usr/bin/env python3
"""Submit and poll the E20 static visual-lock candidate batch.

This runner is deliberately image-only. It refuses to run unless the prompt
contract opens static candidates while keeping video generation closed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_URL = os.environ.get("GIGGLE_API_BASE", "https://giggle.pro").rstrip("/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(
    method: str,
    path: str,
    token: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={
            "x-auth": token,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://giggle.pro",
            "Referer": "https://giggle.pro/",
            "User-Agent": "qingshan-e20-static-lock-batch/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc


def download(url: str, out_path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "qingshan-e20-static-lock-batch/1.0"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        out_path.write_bytes(response.read())


def image_ext(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".png"


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_tasks(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    if contract.get("generation_allowed") is not False:
        raise ValueError("Video generation gate must remain closed.")
    if contract.get("static_candidate_generation_allowed") is not True:
        raise ValueError("Static candidate gate is not open.")

    positive = ", ".join(contract.get("global_positive", []))
    global_negative = contract.get("global_negative", [])
    tasks: List[Dict[str, Any]] = []
    for lock in contract.get("lock_prompts", []):
        references = []
        if lock.get("reference_image"):
            references.append(lock["reference_image"])
        references.extend((lock.get("references") or {}).values())
        for view in lock.get("views", []):
            negatives = global_negative + lock.get("hard_negative", [])
            prompt = (
                f"{positive}. {view['VISUAL_PROMPT_NO_DIALOGUE_TEXT']} "
                f"Hard exclusions: {', '.join(negatives)}."
            )
            tasks.append(
                {
                    "lock_id": lock["lock_id"],
                    "view_id": view["view_id"],
                    "purpose": view["purpose"],
                    "prompt": prompt,
                    "reference_images": references,
                    "reference_video": lock.get("reference_video"),
                }
            )
    expected = int(contract.get("expected_task_count", 15))
    if len(tasks) != expected:
        raise ValueError(f"Expected {expected} static views, found {len(tasks)}.")
    return tasks


def ffmpeg_binary(base: Path) -> str:
    result = subprocess.run(
        [str(base / "tools" / "find_ffmpeg.sh")],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def prepare_references(task: Dict[str, Any], base: Path, out_dir: Path) -> List[Path]:
    refs = [Path(value).expanduser().resolve() for value in task["reference_images"]]
    video = task.get("reference_video")
    if video:
        frame = out_dir / "references" / f"{task['lock_id']}.jpg"
        if not frame.exists():
            frame.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    ffmpeg_binary(base),
                    "-y",
                    "-ss",
                    "2.0",
                    "-i",
                    str(Path(video).expanduser().resolve()),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        refs.append(frame)
    for path in refs:
        if not path.exists():
            raise FileNotFoundError(path)
    return refs


def submit_one(task: Dict[str, Any], refs: List[Path], token: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "prompt": task["prompt"],
        "generate_count": 1,
        "model": "gpt-image-2-pro",
        "aspect_ratio": "9:16",
        "resolution": "1K",
        "watermark": False,
    }
    endpoint = "/api/v1/generation/text-to-image"
    if refs:
        endpoint = "/api/v1/generation/image-to-image"
        payload["reference_images"] = [{"base64": image_base64(path)} for path in refs]
    response = request_json("POST", endpoint, token, payload)
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("Submit response missing data.task_id")
    return {
        "lock_id": task["lock_id"],
        "view_id": task["view_id"],
        "purpose": task["purpose"],
        "task_id": task_id,
        "status": "submitted",
        "reference_images": [str(path) for path in refs],
        "prompt_sha256": hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest(),
    }


def submit_batch(args: argparse.Namespace) -> int:
    base = Path(args.base).resolve()
    contract_path = Path(args.contract).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    tasks = build_tasks(contract)

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "task_count": len(tasks)}, ensure_ascii=False))
        return 0

    token = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not token:
        raise SystemExit("GIGGLE_API_KEY is not set")
    prepared = [(task, prepare_references(task, base, out_dir)) for task in tasks]
    submitted = []
    failures = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_map = {
            executor.submit(submit_one, task, refs, token): task
            for task, refs in prepared
        }
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                submitted.append(future.result())
            except Exception as exc:
                failures.append(
                    {
                        "lock_id": task["lock_id"],
                        "view_id": task["view_id"],
                        "error": str(exc),
                    }
                )

    status = {
        "episode": contract.get("episode", "E20"),
        "mode": "STATIC_CANDIDATES_ONLY",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "contract": str(contract_path),
        "contract_sha256": sha256(contract_path),
        "submitted": sorted(submitted, key=lambda item: item["view_id"]),
        "failures": sorted(failures, key=lambda item: item["view_id"]),
        "video_generation_allowed": False,
    }
    write_json_atomic(Path(args.status).resolve(), status)
    print(json.dumps({"submitted": len(submitted), "failed": len(failures), "status": args.status}, ensure_ascii=False))
    return 0 if not failures else 1


def collect_batch(args: argparse.Namespace) -> int:
    status_path = Path(args.status).resolve()
    out_dir = Path(args.out_dir).resolve()
    status = json.loads(status_path.read_text(encoding="utf-8"))
    token = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not token:
        raise SystemExit("GIGGLE_API_KEY is not set")

    completed = 0
    pending = 0
    failed = 0
    for item in status.get("submitted", []):
        query = urllib.parse.urlencode({"task_id": item["task_id"]})
        response = request_json(
            "GET",
            f"/api/v1/generation/task/query?{query}",
            token,
        )
        data = response.get("data") or {}
        remote_status = str(data.get("status", "unknown"))
        item["status"] = remote_status
        item["giggle_receipt"] = {
            "code": response.get("code"),
            "uuid": response.get("uuid"),
            "task_id": data.get("task_id"),
            "asset_ids": [
                asset.get("asset_id")
                for asset in data.get("asset_info") or []
                if asset.get("asset_id")
            ],
        }
        if remote_status == "completed":
            asset_info = data.get("asset_info") or []
            urls = data.get("urls") or []
            source_url = ""
            extension_url = ""
            if asset_info:
                source_url = (
                    asset_info[0].get("download_url")
                    or asset_info[0].get("signed_url")
                    or asset_info[0].get("download_url_shorter")
                    or ""
                )
                extension_url = asset_info[0].get("signed_url") or source_url
            if not source_url and urls:
                source_url = urls[0]
                extension_url = source_url
            if not source_url:
                item["status"] = "completed_without_url"
                item["error"] = "Completed task returned no downloadable asset."
                failed += 1
                continue
            target_dir = out_dir / item["lock_id"]
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{item['view_id']}{image_ext(extension_url)}"
            if not target.exists():
                download(source_url, target)
            item["result_image_path"] = str(target)
            item["image_sha256"] = sha256(target)
            item["image_bytes"] = target.stat().st_size
            completed += 1
        elif remote_status in {"failed", "error", "canceled", "cancelled"}:
            item["error"] = data.get("err_msg") or "Remote generation failed."
            failed += 1
        else:
            pending += 1
        write_json_atomic(status_path, status)

    status["collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    status["collection_summary"] = {
        "completed": completed,
        "pending": pending,
        "failed": failed,
    }
    write_json_atomic(status_path, status)
    print(
        json.dumps(
            {
                "completed": completed,
                "pending": pending,
                "failed": failed,
                "status": str(status_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="/Users/rogerwu/qingshan_short_drama")
    parser.add_argument(
        "--contract",
        default="/Users/rogerwu/qingshan_short_drama/configs/e20_visual_lock_prompt_drafts_v0_20260716.json",
    )
    parser.add_argument(
        "--out-dir",
        default="/Users/rogerwu/qingshan_short_drama/working_assets/e20_static_visual_lock_candidates_20260716",
    )
    parser.add_argument(
        "--status",
        default="/Users/rogerwu/qingshan_short_drama/working_assets/e20_static_visual_lock_candidates_20260716/E20_STATIC_CANDIDATE_BATCH_STATUS.json",
    )
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    if args.collect:
        return collect_batch(args)
    return submit_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
