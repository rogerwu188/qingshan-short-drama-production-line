#!/usr/bin/env python3
"""Generate and QA zero-credit U25 DIA-018 Kokoro audition/reference audio."""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base


ROOT = Path(__file__).resolve().parents[1]
TEXT = "查借印的手，你我同路。阿栓，我带走。"
VOICE = "zm_009"
SPEEDS = (0.92, 1.0, 1.08)
TARGET_DURATION = 4.5
OUT = ROOT / "working_assets/e40_production_20260814/u25_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u25_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u25_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U25_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U25_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U25_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
SELECTED = PROD_QA / "E40_U25_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"


def generate() -> int:
    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline

    if RECEIPT.exists():
        raise SystemExit("FAIL_CLOSED_RECEIPT_COLLISION")
    OUT.mkdir(parents=True, exist_ok=True)
    config = base.download("config.json")
    weights = base.download("kokoro-v1_1-zh.pth")
    readme = base.download("README.md")
    voice_path = base.download(f"voices/{VOICE}.pt")
    if base.sha(weights) != base.WEIGHTS_SHA:
        raise SystemExit("FAIL_CLOSED_MODEL_SHA")
    rights = {
        "schema": "qingshan.e40.u25.parallel.kokoro_commercial_rights_evidence.v1",
        "episode": "E40",
        "unit_id": "U25",
        "dialogue_id": "E40-DIA-018",
        "speaker": "陈迹",
        "status": "PASS_RELEASE_CLEAR_APACHE_2_0_BUILT_IN_VOICE",
        "created_at": base.now(),
        "model_repo": base.REPO,
        "pinned_revision": base.REVISION,
        "model_weights_sha256": base.sha(weights),
        "model_card_sha256": base.sha(readme),
        "model_card_license": "apache-2.0",
        "license_source": "https://raw.githubusercontent.com/hexgrad/kokoro/main/LICENSE",
        "license_text_sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        "voice_type": "BUILT_IN_MODEL_CHINESE_MALE_SPEAKER_NOT_USER_CLONE",
        "voices": [VOICE],
        "continuity_basis": "Preserve admitted E40 U05-U09/U12/U15 Chenji voice identity with built-in zm_009.",
        "performance_contract": "20-year-old male, medium-low cold steady register; two firm decisions with natural clause break, no announcer delivery and no rushed final words.",
        "releaseBlocked": False,
        "provider_posts": 0,
        "provider_credits": 0
    }
    base.atomic_json(RIGHTS, rights)
    torch.manual_seed(40)
    model = KModel(repo_id=base.REPO, config=str(config), model=str(weights)).to("cpu").eval()
    pipeline = KPipeline(lang_code="z", repo_id=base.REPO, model=model)
    voice_tensor = torch.load(voice_path, map_location="cpu", weights_only=True)
    outputs = []
    for speed in SPEEDS:
        result = next(pipeline(TEXT, voice=voice_tensor, speed=speed))
        tag = str(speed).replace(".", "p")
        source = OUT / f"E40-DIA018_{VOICE}_speed{tag}_source24k.wav"
        normalized = OUT / f"E40-DIA018_{VOICE}_speed{tag}_normalized48k.wav"
        sf.write(source, result.audio.detach().cpu().numpy(), 24000)
        subprocess.run(
            [base.FFMPEG, "-y", "-v", "error", "-i", str(source), "-af", "loudnorm=I=-18:TP=-2:LRA=7", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(normalized)],
            check=True,
        )
        outputs.append(
            {
                "voice": VOICE,
                "speed": speed,
                "source_path": str(source.relative_to(ROOT)),
                "source_sha256": base.sha(source),
                "normalized_path": str(normalized.relative_to(ROOT)),
                "normalized_sha256": base.sha(normalized),
                "voice_file_sha256": base.sha(voice_path),
            }
        )
    payload = {
        "schema": "qingshan.e40.u25.parallel.kokoro_candidate_generation.v1",
        "episode": "E40",
        "unit_id": "U25",
        "scene_id": "13-5",
        "dialogue_id": "E40-DIA-018",
        "speaker": "陈迹",
        "status": "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING",
        "created_at": base.now(),
        "expected_text": TEXT,
        "target_duration_seconds": TARGET_DURATION,
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": base.sha(RIGHTS),
        "outputs": outputs,
        "mode": "LOCAL_KOKORO_ZERO_PROVIDER_POST",
        "intended_use": "AUDITION_AND_DIALOGUE_REFERENCE_ONLY_NATIVE_VIDEO_LIP_SYNC_REMAINS_REQUIRED",
        "provider_posts": 0,
        "credits": 0
    }
    base.atomic_json(RECEIPT, payload)
    print(json.dumps({"status": payload["status"], "candidates": len(outputs)}, ensure_ascii=False))
    return 0


def machine_failures(similarity: float, audio: dict) -> list[str]:
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NOT_EXACT")
    if not 3.5 <= audio["duration_seconds"] <= 5.5:
        failures.append("DURATION_OUTSIDE_3P5_TO_5P5")
    if audio["integrated_lufs"] is None or not -19.5 <= audio["integrated_lufs"] <= -16.0:
        failures.append("LOUDNESS_FAIL")
    if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
        failures.append("TRUE_PEAK_FAIL")
    return failures


def qa() -> int:
    from faster_whisper import WhisperModel

    if not RECEIPT.is_file() or QA.exists():
        raise SystemExit("FAIL_CLOSED_RECEIPT_MISSING_OR_QA_COLLISION")
    model = WhisperModel(str(base.WHISPER), device="cpu", compute_type="int8", local_files_only=True)
    rows = []
    for item in json.loads(RECEIPT.read_text(encoding="utf-8"))["outputs"]:
        path = ROOT / item["normalized_path"]
        segments, _ = model.transcribe(str(path), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT)
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, base.norm(TEXT), base.norm(transcript)).ratio()
        audio = base.metrics(path)
        failures = machine_failures(similarity, audio)
        rows.append({**item, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "audio_metrics": audio, "status": "PASS_MACHINE" if not failures else "FAIL", "failures": failures})
    passes = [row for row in rows if row["status"] == "PASS_MACHINE"]
    passes.sort(key=lambda row: (abs(row["audio_metrics"]["duration_seconds"] - TARGET_DURATION), row["speed"]))
    selected = passes[0] if passes else None
    payload = {
        "schema": "qingshan.e40.u25.parallel.kokoro_exact_audio_machine_qa.v1",
        "episode": "E40",
        "unit_id": "U25",
        "scene_id": "13-5",
        "dialogue_id": "E40-DIA-018",
        "speaker": "陈迹",
        "status": "PASS_MACHINE_SELECTION" if selected else "FAIL_NO_CANDIDATE",
        "created_at": base.now(),
        "expected_text": TEXT,
        "target_duration_seconds": TARGET_DURATION,
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": base.sha(RIGHTS),
        "candidates": rows,
        "selected": selected,
        "selection_rule": "exact normalized ASR and audio gates; preserve admitted Chenji zm_009 identity; duration nearest canonical 4.5s",
        "transport_scope": "AUDITION_REFERENCE_ONLY_MODEL_NATIVE_EXACT_LINE_AND_VISIBLE_LIP_SYNC_STILL_REQUIRED",
        "provider_posts": 0,
        "credits": 0
    }
    base.atomic_json(QA, payload)
    if selected:
        base.atomic_json(
            SELECTED,
            {
                "schema": "qingshan.e40.u25.parallel.kokoro_selected_audio_receipt.v1",
                "status": "PASS_MACHINE_SELECTED_REFERENCE_AUDIO",
                "created_at": base.now(),
                "episode": "E40",
                "unit_id": "U25",
                "scene_id": "13-5",
                "dialogue_id": "E40-DIA-018",
                "speaker": "陈迹",
                "exact_text": TEXT,
                "selected": selected,
                "machine_qa_path": str(QA.relative_to(ROOT)),
                "machine_qa_sha256": base.sha(QA),
                "rights_evidence_path": str(RIGHTS.relative_to(ROOT)),
                "rights_evidence_sha256": base.sha(RIGHTS),
                "provider_posts": 0,
                "credits": 0,
                "final_video_transport": "MODEL_NATIVE_EXACT_LINE_REQUIRED_REFERENCE_AUDIO_NOT_AGENTCUT_OVERLAY"
            },
        )
    print(json.dumps({"status": payload["status"], "passes": len(passes), "selected": selected and selected["normalized_path"]}, ensure_ascii=False))
    return 0 if selected else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true")
    group.add_argument("--qa", action="store_true")
    args = parser.parse_args()
    return generate() if args.generate else qa()


if __name__ == "__main__":
    raise SystemExit(main())
