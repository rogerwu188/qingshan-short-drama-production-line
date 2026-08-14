#!/usr/bin/env python3
"""Generate exact role-bound E33 dialogue references for Seedance lip sync."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import edge_tts


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v1_20260723/E33_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
WORK = ROOT / "working_assets/e33_dialogue_audio_refs_20260723"
MANIFEST = WORK / "E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = FFMPEG.with_name("ffprobe")

VOICE = {
    "陈迹": ("zh-CN-YunxiNeural", "+8%", "-4Hz"),
    "皎兔": ("zh-CN-XiaoyiNeural", "+6%", "+4Hz"),
    "云羊": ("zh-CN-YunxiaNeural", "+8%", "+2Hz"),
}

DIALOGUE = [
    ("E33-DIA-001", "E33-CW-U02", "云羊", "四门全落锁了，硬闯就是拿命填。", "低喝，焦急但保持判断力"),
    ("E33-DIA-002", "E33-CW-U03", "陈迹", "密谍司的巡检旗、景朝暗桩混在里头、还有内院的私兵……他们把三拨谁也不信谁的人，塞进了同一张网。", "视线依次锁定三方，后半句寒意加深"),
    ("E33-DIA-003", "E33-CW-U04", "皎兔", "这网太密，闯不出去。", "贴檐压声，急促警觉"),
    ("E33-DIA-004", "E33-CW-U04", "陈迹", "那就不闯。让网里的人，先咬起来。", "先短停，再冷静下令"),
    ("E33-DIA-005", "E33-CW-U05", "陈迹", "一封给巡检兵——景朝暗桩已拿你们的布防去邀功；一封给景朝暗桩——内院私兵要借围猎除掉你们；一封给内院——密谍司要连你们一起收网灭口。三封信，三拨人，各中各的心事。", "逐封说明，节奏清楚，最后一句笃定"),
    ("E33-DIA-006", "E33-CW-U08", "皎兔", "信都到了。就看谁先沉不住气。", "归窍吐气后寒声确认"),
    ("E33-DIA-007", "E33-CW-U08", "陈迹", "不必等太久。互相咬着的人，一点就着。", "望向骚动，平静而肯定"),
    ("E33-DIA-008", "E33-CW-U15", "云羊", "拿到了！走——趁他们还没顾上咱们！", "护住侧翼，喘息中急喝"),
    ("E33-DIA-009", "E33-CW-U16", "皎兔", "姚太医的乌鸦——它在指路。", "先惊讶，随即确认"),
    ("E33-DIA-010", "E33-CW-U18", "陈迹", "收网的人，今夜要自己收拾自己了。", "入洞前回望，低声冷定"),
    ("E33-DIA-011", "E33-CW-U19", "云羊", "真的……全在这儿。从今夜起，是他们该怕了。", "前半震惊发颤，后半转为振奋"),
    ("E33-DIA-012", "E33-CW-U20", "陈迹", "景朝的水波纹……连密谍司自己的内鬼名册，最顶上那个名字，都是景朝替他封的。", "尝试失败后沉声确认"),
    ("E33-DIA-013", "E33-CW-U20", "皎兔", "等等——这里。", "突然发现旁注，压低惊呼"),
    ("E33-DIA-014", "E33-CW-U21", "陈迹", "沈砚……我凭空编的那个名字。它怎么会……压在整本内鬼名册的最上头，成了一桩景朝的旧案？", "瞳孔骤缩，从不信转为森然失神"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


async def generate() -> list[dict[str, object]]:
    raw_dir = WORK / "raw"
    wav_dir = WORK / "wav"
    raw_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    for dia_id, _, speaker, text, _ in DIALOGUE:
        voice, rate, pitch = VOICE[speaker]
        raw = raw_dir / f"{dia_id}.mp3"
        if not raw.is_file():
            pending.append(edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch).save(str(raw)))
    if pending:
        await asyncio.gather(*pending)

    rows = []
    for dia_id, unit_id, speaker, text, performance in DIALOGUE:
        voice, rate, pitch = VOICE[speaker]
        raw = raw_dir / f"{dia_id}.mp3"
        wav = wav_dir / f"{dia_id}.wav"
        subprocess.run(
            [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
             "-af", "highpass=f=75,lowpass=f=12500,loudnorm=I=-18:LRA=7:TP=-2",
             "-ac", "1", "-ar", "48000", str(wav)],
            check=True,
        )
        rows.append({
            "dia_id": dia_id,
            "video_unit_id": unit_id,
            "speaker": speaker,
            "spoken_text": text,
            "performance": performance,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "path": str(wav.relative_to(ROOT)),
            "sha256": sha256(wav),
            "duration_seconds": round(duration(wav), 6),
            "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            "generation_policy": "REFERENCE_AUDIO_FOR_VIDEO_MODEL_NATIVE_MANDARIN_LIP_SYNC",
            "remote_call_credit": "UNKNOWN",
            "remote_call_credit_reason": "EDGE_TTS_SUCCESS_RESPONSE_HAS_NO_CREDIT_FIELD",
            "status": "PASS",
        })
    return rows


def main() -> int:
    rows = asyncio.run(generate())
    by_unit: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_unit.setdefault(str(row["video_unit_id"]), []).append(row)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for unit_row in plan["units"]:
        assets = by_unit.get(unit_row["unit_id"], [])
        unit_row["dialogue_ids"] = [row["dia_id"] for row in assets]
        unit_row["native_dialogue_required"] = bool(assets)
        unit_row["dialogue_audio_assets"] = [
            {key: row[key] for key in ("dia_id", "path", "sha256", "speaker", "spoken_text")}
            for row in assets
        ]
        unit_row["reference_audios"] = [row["path"] for row in assets]
        unit_row["dialogue_audio_reference_status"] = "PASS" if assets else "NOT_REQUIRED"
        unit_row["dialogue_audio_coverage"] = {
            "required": len(assets),
            "bound": len(assets),
            "status": "PASS" if assets else "NOT_APPLICABLE_NO_DIALOGUE",
        }
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps({
        "schema": "qingshan.dialogue_audio_reference_manifest.v1",
        "episode": "E33",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "dialogue_line_count": len(rows),
        "remote_call_count": len(rows),
        "remote_call_credit_known_total": 0,
        "remote_call_credit_unknown_count": len(rows),
        "credit_policy": "UNKNOWN_RECORDED_NOT_ESTIMATED",
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "dialogue_lines": len(rows),
        "bound_units": len(by_unit),
        "remote_credit": "UNKNOWN_NOT_ESTIMATED",
        "manifest": str(MANIFEST.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
