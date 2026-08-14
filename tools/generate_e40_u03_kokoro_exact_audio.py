#!/usr/bin/env python3
"""Generate the rights-cleared exact Yunfei line for E40 U03 at zero credit."""

from __future__ import annotations

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
REPO = "hexgrad/Kokoro-82M-v1.1-zh"
REVISION = "01e7505bd6a7a2ac4975463114c3a7650a9f7218"
WEIGHTS_SHA = "b1d8410fa44dfb5c15471fd6c4225ea6b4e9ac7fa03c98e8bea47a9928476e2b"
TEXT = "换，还是不换？"
VOICE = "zf_001"
SPEED = 1.28
OUT = ROOT / "working_assets/e40_production_20260814/u03_v1_kokoro_rights_cleared_exact_audio_v1"
SOURCE = OUT / "E40-DIA-003_zf_001_source24k.wav"
WAV = OUT / "E40-DIA-003_zf_001_normalized48k.wav"
RECEIPT = ROOT / "workflow/tasks/E40_U03_DIA003_KOKORO_RIGHTS_CLEARED_EXACT_AUDIO_GENERATION_20260814.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"


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


def main() -> int:
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    if rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_RIGHTS")
    config = Path(hf_hub_download(repo_id=REPO, filename="config.json", revision=REVISION))
    weights = Path(hf_hub_download(repo_id=REPO, filename="kokoro-v1_1-zh.pth", revision=REVISION))
    voice = Path(hf_hub_download(repo_id=REPO, filename=f"voices/{VOICE}.pt", revision=REVISION))
    if sha256(weights) != WEIGHTS_SHA:
        raise SystemExit("FAIL_CLOSED_MODEL_SHA")
    OUT.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(40)
    model = KModel(repo_id=REPO, config=str(config), model=str(weights)).to("cpu").eval()
    pipeline = KPipeline(lang_code="z", repo_id=REPO, model=model)
    voice_tensor = torch.load(voice, map_location="cpu", weights_only=True)
    result = next(pipeline(TEXT, voice=voice_tensor, speed=SPEED))
    sf.write(SOURCE, result.audio.detach().cpu().numpy(), 24000)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(SOURCE),
        "-af", "loudnorm=I=-18:TP=-2:LRA=7", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(WAV),
    ], check=True)
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u03.dia003.kokoro_exact_audio_generation.v1",
        "status": "PASS_ZERO_CREDIT_GENERATED_QA_PENDING",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "episode": "E40", "unit": "U03", "line_id": "E40-DIA-003",
        "exact_text": TEXT, "voice": VOICE, "speed": SPEED,
        "model_repo": REPO, "pinned_revision": REVISION, "model_weights_sha256": sha256(weights),
        "rights_evidence": str(RIGHTS.relative_to(ROOT)), "rights_evidence_sha256": sha256(RIGHTS),
        "source": str(SOURCE.relative_to(ROOT)), "source_sha256": sha256(SOURCE),
        "output": str(WAV.relative_to(ROOT)), "output_sha256": sha256(WAV),
        "provider_post_count": 0, "credits": 0,
    })
    print(json.dumps({"status": "PASS_ZERO_CREDIT_GENERATED_QA_PENDING", "output": str(WAV), "sha256": sha256(WAV)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
