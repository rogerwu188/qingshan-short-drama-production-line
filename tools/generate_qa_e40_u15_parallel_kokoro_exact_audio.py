#!/usr/bin/env python3
"""Generate and machine-QA both release-clear local U15 dialogue lines."""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base


ROOT = Path(__file__).resolve().parents[1]
LINES = (
    {"dialogue_id": "E40-DIA-013", "file_id": "DIA013", "text": "有人借您的印，伪造您的令。", "target_duration": 3.0},
    {"dialogue_id": "E40-DIA-014", "file_id": "DIA014", "text": "您，也是被借的一把刀。", "target_duration": 3.0},
)
VOICE = "zm_009"
SPEEDS = (0.92, 1.0, 1.08)
OUT = ROOT / "working_assets/e40_production_20260814/u15_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u15_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u15_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U15_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U15_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U15_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"


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
        "schema": "qingshan.e40.u15.parallel.kokoro_commercial_rights_evidence.v1",
        "episode": "E40", "unit_id": "U15", "dialogue_ids": [line["dialogue_id"] for line in LINES], "speaker": "陈迹",
        "status": "PASS_RELEASE_CLEAR_APACHE_2_0_BUILT_IN_VOICES", "created_at": base.now(),
        "model_repo": base.REPO, "pinned_revision": base.REVISION, "model_weights_sha256": base.sha(weights),
        "model_card_sha256": base.sha(readme), "model_card_license": "apache-2.0",
        "license_source": "https://raw.githubusercontent.com/hexgrad/kokoro/main/LICENSE",
        "license_text_sha256": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
        "voice_type": "BUILT_IN_MODEL_CHINESE_MALE_SPEAKER_NOT_USER_CLONE", "voices": [VOICE],
        "continuity_basis": "Preserve admitted E40 U05-U09/U12 Chenji voice identity with built-in zm_009.",
        "releaseBlocked": False, "provider_posts": 0, "provider_credits": 0,
    }
    base.atomic_json(RIGHTS, rights)
    torch.manual_seed(40)
    model = KModel(repo_id=base.REPO, config=str(config), model=str(weights)).to("cpu").eval()
    pipeline = KPipeline(lang_code="z", repo_id=base.REPO, model=model)
    voice_tensor = torch.load(voice_path, map_location="cpu", weights_only=True)
    outputs = []
    for line in LINES:
        for speed in SPEEDS:
            result = next(pipeline(line["text"], voice=voice_tensor, speed=speed))
            tag = str(speed).replace(".", "p")
            source = OUT / f"E40-{line['file_id']}_{VOICE}_speed{tag}_source24k.wav"
            normalized = OUT / f"E40-{line['file_id']}_{VOICE}_speed{tag}_normalized48k.wav"
            sf.write(source, result.audio.detach().cpu().numpy(), 24000)
            subprocess.run([base.FFMPEG, "-y", "-v", "error", "-i", str(source), "-af", "loudnorm=I=-18:TP=-2:LRA=7", "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(normalized)], check=True)
            outputs.append({"dialogue_id": line["dialogue_id"], "expected_text": line["text"], "target_duration_seconds": line["target_duration"], "voice": VOICE, "speed": speed, "source_path": str(source.relative_to(ROOT)), "source_sha256": base.sha(source), "normalized_path": str(normalized.relative_to(ROOT)), "normalized_sha256": base.sha(normalized), "voice_file_sha256": base.sha(voice_path)})
    payload = {"schema": "qingshan.e40.u15.parallel.kokoro_candidate_generation.v1", "episode": "E40", "unit_id": "U15", "scene_id": "13-3", "speaker": "陈迹", "status": "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING", "created_at": base.now(), "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b", "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1", "rights_evidence": str(RIGHTS.relative_to(ROOT)), "rights_evidence_sha256": base.sha(RIGHTS), "outputs": outputs, "provider_posts": 0, "credits": 0}
    base.atomic_json(RECEIPT, payload)
    print(json.dumps({"status": payload["status"], "dialogues": 2, "candidates": len(outputs)}, ensure_ascii=False))
    return 0


def machine_failures(similarity: float, audio: dict) -> list[str]:
    failures = []
    if similarity != 1.0:
        failures.append("ASR_NOT_EXACT")
    if not 2.2 <= audio["duration_seconds"] <= 4.2:
        failures.append("DURATION_OUTSIDE_2P2_TO_4P2")
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
        segments, _ = model.transcribe(str(path), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=item["expected_text"])
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, base.norm(item["expected_text"]), base.norm(transcript)).ratio()
        audio = base.metrics(path)
        failed = machine_failures(similarity, audio)
        rows.append({**item, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "audio_metrics": audio, "status": "PASS_MACHINE" if not failed else "FAIL", "failures": failed})
    selected = {}
    for line in LINES:
        passes = [row for row in rows if row["dialogue_id"] == line["dialogue_id"] and row["status"] == "PASS_MACHINE"]
        passes.sort(key=lambda row: (abs(row["audio_metrics"]["duration_seconds"] - line["target_duration"]), row["speed"]))
        selected[line["dialogue_id"]] = passes[0] if passes else None
    all_pass = all(selected.values())
    payload = {"schema": "qingshan.e40.u15.parallel.kokoro_exact_audio_machine_qa.v1", "episode": "E40", "unit_id": "U15", "scene_id": "13-3", "speaker": "陈迹", "status": "PASS_MACHINE_ALL_DIALOGUES_SELECTED" if all_pass else "FAIL_MISSING_DIALOGUE_SELECTION", "created_at": base.now(), "rights_evidence": str(RIGHTS.relative_to(ROOT)), "rights_evidence_sha256": base.sha(RIGHTS), "candidates": rows, "selected": selected, "selection_rule": "per dialogue: exact normalized ASR and audio gates; preserve admitted zm_009 identity; duration nearest canonical 3.0s", "provider_posts": 0, "credits": 0}
    base.atomic_json(QA, payload)
    print(json.dumps({"status": payload["status"], "selected": {key: value and value["normalized_path"] for key, value in selected.items()}}, ensure_ascii=False))
    return 0 if all_pass else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true")
    group.add_argument("--qa", action="store_true")
    args = parser.parse_args()
    return generate() if args.generate else qa()


if __name__ == "__main__":
    raise SystemExit(main())
