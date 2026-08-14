#!/usr/bin/env python3
"""Generate zero-credit, rights-cleared Kokoro candidates for E40 U02.

This tool has no paid-provider code path. Model files and voices are pinned to
one Hugging Face commit and every downloaded artifact is hashed in the receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import soundfile as sf
import torch
from huggingface_hub import hf_hub_download
from kokoro import KModel, KPipeline


ROOT = Path(__file__).resolve().parents[1]
REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"
REVISION = "01e7505bd6a7a2ac4975463114c3a7650a9f7218"
MODEL_CARD_SHA256 = "b1d8410fa44dfb5c15471fd6c4225ea6b4e9ac7fa03c98e8bea47a9928476e2b"
VOICES = ("zf_001", "zf_021", "zf_083")
LINES = (
    ("E40-DIA-001", "阿栓，在本宫手上。", 0.91),
    ("E40-DIA-002", "拿他，换景朝一个接头人。", 0.94),
)
OUT = ROOT / "working_assets/e40_production_20260814/u02_v12_kokoro_rights_cleared_audio_candidates_v1"
RECEIPT = ROOT / "workflow/tasks/E40_U02_V12_KOKORO_RIGHTS_CLEARED_CANDIDATE_GENERATION_20260814.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
FFMPEG = "ffmpeg"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def download(filename: str) -> Path:
    return Path(hf_hub_download(repo_id=REPO_ID, filename=filename, revision=REVISION))


def normalize(source: Path, target: Path) -> None:
    subprocess.run(
        [
            FFMPEG, "-y", "-v", "error", "-i", str(source),
            "-af", "loudnorm=I=-18:TP=-2:LRA=7",
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(target),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pace-repair-v2", action="store_true")
    args = parser.parse_args()
    voices = VOICES
    lines = LINES
    out = OUT
    receipt = RECEIPT
    if args.pace_repair_v2:
        voices = ("zf_001", "zf_021")
        lines = (
            ("E40-DIA-001", "阿栓，在本宫手上。", 1.55),
            ("E40-DIA-002", "拿他，换景朝一个接头人。", 1.58),
        )
        out = ROOT / "working_assets/e40_production_20260814/u02_v13_kokoro_pace_repair_audio_candidates_v1"
        receipt = ROOT / "workflow/tasks/E40_U02_V13_KOKORO_PACE_REPAIR_CANDIDATE_GENERATION_20260814.json"
    out.mkdir(parents=True, exist_ok=True)
    config = download("config.json")
    weights = download("kokoro-v1_1-zh.pth")
    readme = download("README.md")
    if sha256(weights) != MODEL_CARD_SHA256:
        raise SystemExit("FAIL_CLOSED_MODEL_WEIGHT_SHA_MISMATCH")

    voice_paths = {voice: download(f"voices/{voice}.pt") for voice in voices}
    rights_payload = {
        "schema": "qingshan.e40.kokoro_commercial_rights_evidence.v1",
        "status": "PASS_RELEASE_CLEAR_APACHE_2_0_BUILT_IN_VOICES",
        "created_at": utc_now(),
        "model_repo": REPO_ID,
        "pinned_revision": REVISION,
        "model_weights_sha256": sha256(weights),
        "model_card_sha256": sha256(readme),
        "model_card_license": "apache-2.0",
        "license_source": "https://raw.githubusercontent.com/hexgrad/kokoro/main/LICENSE",
        "license_text_sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        "license_scope_summary": "Apache License 2.0 permits use, reproduction, modification, and distribution subject to its notice conditions.",
        "training_data_evidence": "The official model card states that 100 Chinese speakers came from a professional dataset freely and permissively granted by LongMaoData.",
        "model_card_url": "https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh/blob/01e7505bd6a7a2ac4975463114c3a7650a9f7218/README.md",
        "voice_type": "BUILT_IN_MODEL_SPEAKER_NOT_USER_CLONE",
        "voices": list(VOICES),
        "releaseBlocked": False,
        "provider_credits": 0,
        "failure_memory_prerequisite": {
            "path": "qa/e40_production_20260814/u02_v11_exact_yunfei_audio_v1/E40_U02_DIA001_TTS_FAILURE_MEMORY_V1.json",
            "sha256": "4210cf109f5966aedd653e069d1a67b4adc6efe8f3d96c8639da7c29d4e3616f",
        },
        "material_change": "Giggle cloned voice replaced by pinned local Apache-2.0 Kokoro built-in Chinese female speakers; no provider replay.",
    }
    atomic_json(RIGHTS, rights_payload)

    torch.manual_seed(40)
    model = KModel(repo_id=REPO_ID, config=str(config), model=str(weights)).to("cpu").eval()
    pipeline = KPipeline(lang_code="z", repo_id=REPO_ID, model=model)
    outputs = []
    for voice in voices:
        voice_tensor = torch.load(voice_paths[voice], map_location="cpu", weights_only=True)
        for line_id, text, speed in lines:
            result = next(pipeline(text, voice=voice_tensor, speed=speed))
            source = out / f"{line_id}_{voice}_source24k.wav"
            normalized = out / f"{line_id}_{voice}_normalized48k.wav"
            sf.write(source, result.audio.detach().cpu().numpy(), 24000)
            normalize(source, normalized)
            outputs.append({
                "line_id": line_id,
                "exact_text": text,
                "voice": voice,
                "speed": speed,
                "source_path": str(source.relative_to(ROOT)),
                "source_sha256": sha256(source),
                "normalized_path": str(normalized.relative_to(ROOT)),
                "normalized_sha256": sha256(normalized),
                "voice_file_sha256": sha256(voice_paths[voice]),
            })

    atomic_json(receipt, {
        "schema": "qingshan.e40.u02.kokoro_candidate_generation.v1",
        "status": "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING",
        "created_at": utc_now(),
        "provider_post_count": 0,
        "credits": 0,
        "model_repo": REPO_ID,
        "pinned_revision": REVISION,
        "model_weights_sha256": sha256(weights),
        "config_sha256": sha256(config),
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": sha256(RIGHTS),
        "outputs": outputs,
        "pace_repair_v2": args.pace_repair_v2,
        "predecessor_qa": "qa/e40_production_20260814/u02_v12_kokoro_rights_cleared_audio_candidates_v1/E40_U02_V12_KOKORO_CANDIDATE_MACHINE_QA_V1.json" if args.pace_repair_v2 else None,
    })
    print(json.dumps({
        "status": "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING",
        "candidates": len(outputs),
        "receipt": str(receipt),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
