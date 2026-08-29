#!/usr/bin/env python3
"""Bind exact-ASR-passing E40 audio to provider-native public URLs.

Giggle Omni accepts audio/video references by URL.  A generated speech task
already owns a public audio asset, so re-uploading the downloaded WAV and then
passing the new ``asset_id`` creates an unnecessary, provider-incompatible
transport hop.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from giggle_api_client import _get
except ModuleNotFoundError:
    from tools.giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
ASR = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_ASR_QA_V1.json"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_PROVIDER_ASSET_REGISTRY_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    qa = json.loads(ASR.read_text(encoding="utf-8"))
    if qa.get("status") != "PASS" or qa.get("pass_count") != qa.get("item_count"):
        raise SystemExit("Exact dialogue ASR QA is not fully PASS")
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                _get,
                "/api/v1/generation/task/query",
                {"task_id": row["provider_audio_task_id"]},
            ): row
            for row in qa["rows"]
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                response = future.result()
                data = response.get("data") or response
                if data.get("status") != "completed":
                    raise RuntimeError(f"source audio task is not completed: {data.get('status')}")
                assets = data.get("asset_info") or []
                if len(assets) != 1:
                    raise RuntimeError(f"expected one source audio asset, got {len(assets)}")
                asset = assets[0]
                asset_id = str(asset.get("asset_id") or "")
                public_url = str(asset.get("signed_url") or "")
                if not asset_id or not public_url or asset.get("file_type") != "audio":
                    raise RuntimeError("provider-native audio asset_id/public URL/type missing")
                results.append({
                    "audio_key": row["audio_key"],
                    "dialogue_id": row["dialogue_id"],
                    "wav_path": row["wav_path"],
                    "wav_sha256": row["wav_sha256"],
                    "provider_audio_task_id": row["provider_audio_task_id"],
                    "remote_asset_id": asset_id,
                    "public_audio_url": public_url,
                    "transport": "OMNI_AUDIO_PUBLIC_URL",
                    "status": "PASS",
                })
            except Exception as exc:
                results.append({"audio_key": row["audio_key"], "dialogue_id": row["dialogue_id"], "status": "FAIL", "error": f"{type(exc).__name__}:{exc}"})
    results.sort(key=lambda row: row["audio_key"])
    payload = {
        "schema": "qingshan.e40.full_performance_audio_provider_asset_registry.v1",
        "episode": "E40",
        "status": "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL",
        "registered_count": sum(row["status"] == "PASS" for row in results),
        "item_count": len(results),
        "source_asr_qa": str(ASR.relative_to(ROOT)),
        "source_asr_qa_sha256": sha(ASR),
        "items": results,
        "credit_policy": "SOURCE_TASK_ASSET_LOOKUP_ZERO_GENERATION_CREDIT",
        "purpose": "SEEDANCE_SAME_TASK_EXACT_DIALOGUE_REFERENCE_ONLY_NOT_POST_DUB",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "registered": payload["registered_count"], "items": payload["item_count"], "out": str(OUT.relative_to(ROOT)), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
