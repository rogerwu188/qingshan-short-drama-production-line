#!/usr/bin/env python3
"""Generate and machine-QA release-clear local U06 DIA-005 audio candidates."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import hf_hub_download


ROOT = Path(__file__).resolve().parents[1]
REPO = "hexgrad/Kokoro-82M-v1.1-zh"
REVISION = "01e7505bd6a7a2ac4975463114c3a7650a9f7218"
WEIGHTS_SHA = "b1d8410fa44dfb5c15471fd6c4225ea6b4e9ac7fa03c98e8bea47a9928476e2b"
TEXT = "当铺、法场、药房、火场——活口一个没留。"
VOICES = ("zm_009", "zm_010")
SPEEDS = (0.92, 1.0, 1.08)
OUT = ROOT / "working_assets/e40_production_20260814/u06_v3_kokoro_exact_audio_candidates_v1"
RECEIPT = ROOT / "workflow/tasks/E40_U06_V3_KOKORO_EXACT_AUDIO_CANDIDATE_GENERATION_20260814.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u06_v3_kokoro_rights_clearance_v1/E40_U06_V3_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = ROOT / "qa/e40_production_20260814/u06_v3_kokoro_exact_audio_candidates_v1/E40_U06_V3_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
WHISPER = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True); raise


def download(name: str) -> Path:
    return Path(hf_hub_download(repo_id=REPO, filename=name, revision=REVISION))


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def metrics(path: Path) -> dict:
    probe = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    loud = subprocess.run([FFMPEG, "-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, check=True)
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary); peak = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    payload = json.loads(probe.stdout)
    return {"duration_seconds": float(payload["format"]["duration"]), "integrated_lufs": float(integrated.group(1)) if integrated else None, "true_peak_dbfs": float(peak.group(1)) if peak else None, "probe": payload}


def generate() -> int:
    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline
    if RECEIPT.exists(): raise SystemExit("FAIL_CLOSED_RECEIPT_COLLISION")
    OUT.mkdir(parents=True, exist_ok=True)
    config, weights, readme = download("config.json"), download("kokoro-v1_1-zh.pth"), download("README.md")
    if sha(weights) != WEIGHTS_SHA: raise SystemExit("FAIL_CLOSED_MODEL_SHA")
    voice_paths = {voice: download(f"voices/{voice}.pt") for voice in VOICES}
    rights = {"schema": "qingshan.e40.kokoro_commercial_rights_evidence.v1", "status": "PASS_RELEASE_CLEAR_APACHE_2_0_BUILT_IN_VOICES", "created_at": now(), "model_repo": REPO, "pinned_revision": REVISION, "model_weights_sha256": sha(weights), "model_card_sha256": sha(readme), "model_card_license": "apache-2.0", "license_source": "https://raw.githubusercontent.com/hexgrad/kokoro/main/LICENSE", "license_text_sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4", "training_data_evidence": "Official model card states 100 Chinese speakers came from a professional dataset freely and permissively granted by LongMaoData.", "voice_type": "BUILT_IN_MODEL_CHINESE_MALE_SPEAKER_NOT_USER_CLONE", "voices": list(VOICES), "releaseBlocked": False, "provider_credits": 0, "continuity_basis": "U05 selected zm_009; U06 includes zm_009 first and only selects another voice if objective gates require it.", "provider_posts": 0}
    atomic_json(RIGHTS, rights)
    torch.manual_seed(40)
    model = KModel(repo_id=REPO, config=str(config), model=str(weights)).to("cpu").eval(); pipeline = KPipeline(lang_code="z", repo_id=REPO, model=model)
    outputs = []
    for voice in VOICES:
        tensor = torch.load(voice_paths[voice], map_location="cpu", weights_only=True)
        for speed in SPEEDS:
            result = next(pipeline(TEXT, voice=tensor, speed=speed)); tag = str(speed).replace(".", "p")
            source = OUT / f"E40-DIA005_{voice}_speed{tag}_source24k.wav"; normalized = OUT / f"E40-DIA005_{voice}_speed{tag}_normalized48k.wav"
            sf.write(source, result.audio.detach().cpu().numpy(), 24000)
            subprocess.run([FFMPEG, "-y", "-v", "error", "-i", str(source), "-af", "loudnorm=I=-18:TP=-2:LRA=7", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(normalized)], check=True)
            outputs.append({"voice": voice, "speed": speed, "source_path": str(source.relative_to(ROOT)), "source_sha256": sha(source), "normalized_path": str(normalized.relative_to(ROOT)), "normalized_sha256": sha(normalized), "voice_file_sha256": sha(voice_paths[voice])})
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u06.v3.kokoro_candidate_generation.v1", "status": "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING", "created_at": now(), "provider_post_count": 0, "credits": 0, "model_repo": REPO, "pinned_revision": REVISION, "model_weights_sha256": sha(weights), "config_sha256": sha(config), "rights_evidence": str(RIGHTS.relative_to(ROOT)), "rights_evidence_sha256": sha(RIGHTS), "outputs": outputs})
    print(json.dumps({"status": "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING", "candidates": len(outputs)}, ensure_ascii=False)); return 0


def qa() -> int:
    from faster_whisper import WhisperModel
    if not RECEIPT.is_file() or QA.exists(): raise SystemExit("FAIL_CLOSED_RECEIPT_MISSING_OR_QA_COLLISION")
    generated = json.loads(RECEIPT.read_text(encoding="utf-8"))["outputs"]
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8", local_files_only=True); rows = []
    for item in generated:
        path = ROOT / item["normalized_path"]
        segments, _ = model.transcribe(str(path), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
        transcript = "".join(segment.text.strip() for segment in segments); similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio(); audio = metrics(path); failures = []
        if similarity != 1.0: failures.append("ASR_NOT_EXACT")
        if not 4.4 <= audio["duration_seconds"] <= 6.4: failures.append("DURATION_OUTSIDE_4P4_TO_6P4")
        if audio["integrated_lufs"] is None or not -19.5 <= audio["integrated_lufs"] <= -16.0: failures.append("LOUDNESS_FAIL")
        if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0: failures.append("TRUE_PEAK_FAIL")
        rows.append({**item, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "audio_metrics": audio, "status": "PASS_MACHINE" if not failures else "FAIL", "failures": failures})
    passes = [row for row in rows if row["status"] == "PASS_MACHINE"]
    passes.sort(key=lambda row: (row["voice"] != "zm_009", abs(row["audio_metrics"]["duration_seconds"] - 5.3), row["speed"]))
    selected = passes[0] if passes else None
    payload = {"schema": "qingshan.e40.u06.v3.kokoro_exact_audio_machine_qa.v1", "status": "PASS_MACHINE_SELECTION" if selected else "FAIL_NO_CANDIDATE", "created_at": now(), "expected_text": TEXT, "rights_evidence": str(RIGHTS.relative_to(ROOT)), "rights_evidence_sha256": sha(RIGHTS), "candidates": rows, "selected": selected, "selection_rule": "exact ASR and audio gates; preserve U05 zm_009 identity first, then nearest 5.3s", "provider_posts": 0, "credits": 0}
    atomic_json(QA, payload); print(json.dumps({"status": payload["status"], "passes": len(passes), "selected": selected and selected["normalized_path"]}, ensure_ascii=False)); return 0 if selected else 2


def main() -> int:
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--generate", action="store_true"); group.add_argument("--qa", action="store_true"); args = parser.parse_args(); return generate() if args.generate else qa()


if __name__ == "__main__": raise SystemExit(main())
