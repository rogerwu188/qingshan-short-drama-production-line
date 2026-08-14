#!/usr/bin/env python3
"""Generate exact role-bound E32 dialogue references for Seedance lip sync."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import edge_tts


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722/E32_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
WORK = ROOT / "working_assets/e32_dialogue_audio_refs_20260722"
MANIFEST = WORK / "E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = FFMPEG.with_name("ffprobe")

VOICE = {
    "陈迹": ("zh-CN-YunxiNeural", "+8%", "-4Hz"),
    "皎兔": ("zh-CN-XiaoyiNeural", "+6%", "+4Hz"),
    "云羊": ("zh-CN-YunxiaNeural", "+8%", "+2Hz"),
    "齐三": ("zh-CN-YunyangNeural", "+12%", "+3Hz"),
    "姚太医": ("zh-CN-YunyangNeural", "-8%", "-12Hz"),
}

DIALOGUE = [
    ("E32-DIA-001", "E32-CW-U01", "皎兔", "那印你不验？", "倚门压声，疑惑但警觉"),
    ("E32-DIA-002", "E32-CW-U01", "陈迹", "印会说谎，名单不会。验印，是验他想让我看的。验单，才是验他不想让我看的。", "不抬头，冷静笃定"),
    ("E32-DIA-003", "E32-CW-U02", "陈迹", "这一版……是我亲手送进内院的那一版。", "眸色下沉，确认时有短停顿"),
    ("E32-DIA-004", "E32-CW-U02", "皎兔", "可它，是从景朝人的火盆里烧出来的。", "直起身，惊觉"),
    ("E32-DIA-005", "E32-CW-U03", "陈迹", "内院拿我的名单去换我的信任——转头，就把它卖给了景朝。", "一字一顿，寒意加深"),
    ("E32-DIA-006", "E32-CW-U06", "齐三", "陈爷……小的只是替人跑跑腿，传句话……", "连退赔笑，气息发抖"),
    ("E32-DIA-007", "E32-CW-U07", "陈迹", "同一版名单，一封送内院，一封送景朝。你这跑腿，一条道跑两家主子。", "逼近，语速平稳但压迫"),
    ("E32-DIA-008", "E32-CW-U07", "齐三", "不干小的事！骨牌印那道调令……不是内院发的，也不是景朝发的——", "脸色煞白，膝软抢答"),
    ("E32-DIA-009", "E32-CW-U07", "齐三", "那是密谍司巡检指挥的印！发那道令围你的，压根不走云羊那条线——是巡检司里，能越过所有人发令的那位。", "指向骨牌，声音发颤并加速"),
    ("E32-DIA-010", "E32-CW-U10", "云羊", "巡检司的记。发调令的、来灭口的……是同一条线上的人。", "盯住暗记，声音发冷"),
    ("E32-DIA-011", "E32-CW-U10", "陈迹", "他们宁可杀了自己的牙人，也不能让这条线露出名字。", "握紧冻牌，声沉如铁"),
    ("E32-DIA-012", "E32-CW-U12", "姚太医", "巡检指挥的印，出来杀一个牙人——他们不怕你知道有内鬼了。怕的是，你还有工夫慢慢查。", "温和但字字沉重"),
    ("E32-DIA-013", "E32-CW-U13", "陈迹", "丑时快到了。……他们要抢在我撑不住之前，把我逼出来。", "压住反噬喘息，声音仍稳"),
    ("E32-DIA-014", "E32-CW-U14", "姚太医", "来了。密谍司封城了。", "望向窗外，缓慢确认"),
    ("E32-DIA-015", "E32-CW-U15", "皎兔", "他们把城门、医馆、王府侧门全封了。是要把所有知情的人，压进同一个圈里。", "望着灯网，声音发紧"),
    ("E32-DIA-016", "E32-CW-U16", "云羊", "一个圈里，密谍司的巡检线、景朝的暗桩、内院的私兵……全挤在一处。这些人，本就谁也不信谁。", "握拳，焦灼中迅速分析"),
    ("E32-DIA-017", "E32-CW-U16", "陈迹", "他们急着把所有人赶进一张网……可网里这三拨人，谁也不信谁。", "声压最低，由受压转为洞悉"),
    ("E32-DIA-018", "E32-CW-U17", "陈迹", "收网的以为，网里的都是猎物。可要是让网里的三拨人，先信了‘别人才是内奸’——这张网，会替我勒住收网的手。", "几近自语，最后一句笃定"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        check=True, text=True, capture_output=True,
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
            "dia_id": dia_id, "video_unit_id": unit_id, "speaker": speaker, "spoken_text": text,
            "performance": performance, "voice": voice, "rate": rate, "pitch": pitch,
            "path": str(wav.relative_to(ROOT)), "sha256": sha256(wav),
            "duration_seconds": round(duration(wav), 6), "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
            "generation_policy": "REFERENCE_AUDIO_FOR_VIDEO_MODEL_NATIVE_MANDARIN_LIP_SYNC",
            "remote_call_credit": "UNKNOWN", "remote_call_credit_reason": "EDGE_TTS_SUCCESS_RESPONSE_HAS_NO_CREDIT_FIELD",
            "status": "PASS",
        })
    return rows


def main() -> int:
    rows = asyncio.run(generate())
    by_unit: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_unit.setdefault(str(row["video_unit_id"]), []).append(row)
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for unit in plan["units"]:
        assets = by_unit.get(unit["unit_id"], [])
        unit["dialogue_ids"] = [row["dia_id"] for row in assets]
        unit["native_dialogue_required"] = bool(assets)
        unit["dialogue_audio_assets"] = [
            {key: row[key] for key in ("dia_id", "path", "sha256", "speaker", "spoken_text")}
            for row in assets
        ]
        unit["reference_audios"] = [row["path"] for row in assets]
        unit["dialogue_audio_coverage"] = {
            "required": len(assets), "bound": len(assets),
            "status": "PASS" if assets else "NOT_APPLICABLE_NO_DIALOGUE",
        }
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps({
        "schema": "qingshan.dialogue_audio_reference_manifest.v1", "episode": "E32",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "PASS",
        "dialogue_line_count": len(rows), "remote_call_count": len(rows),
        "remote_call_credit_known_total": 0, "remote_call_credit_unknown_count": len(rows),
        "credit_policy": "UNKNOWN_RECORDED_NOT_ESTIMATED", "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "dialogue_lines": len(rows), "bound_units": len(by_unit),
        "remote_credit": "UNKNOWN_NOT_ESTIMATED", "manifest": str(MANIFEST.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
