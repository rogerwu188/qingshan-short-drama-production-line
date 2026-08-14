#!/usr/bin/env python3
"""
Local continuity auditor for short-drama episodes.

Portable by design:
- Requires Python 3.8+ and ffmpeg.
- Does not require OpenCV, numpy, PIL, FastAPI, or web browser access.
- Uses visual fingerprints from extracted frames to flag likely scene/person/prop drift.

The output is intentionally actionable: JSON, Markdown, evidence frames, an HTML
contact sheet, and a repair prompt file that can be used in Giggle storyboard,
shot regeneration, or API fallback.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_FFMPEG_CANDIDATES = [
    "ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    str(
        Path(
            os.environ.get(
                "QINGSHAN_FACTORY_ROOT",
                Path(__file__).resolve().parents[1],
            )
        )
        / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
    ),
]

DEFAULT_THRESHOLDS = {
    "scene_warn": 0.34,
    "scene_fail": 0.46,
    "character_warn": 0.42,
    "character_fail": 0.55,
    "prop_warn": 0.40,
    "prop_fail": 0.52,
}


@dataclasses.dataclass
class Shot:
    shot_id: str
    start: float
    end: float
    title: str = ""
    scene_id: str = ""
    scene_group_id: str = ""
    room_id: str = ""
    zone_id: str = ""
    angle_id: str = ""
    characters: List[str] = dataclasses.field(default_factory=list)
    props: List[str] = dataclasses.field(default_factory=list)
    dialogue: str = ""
    repair_prompt: str = ""
    repair_stage: str = "storyboard"
    notes: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def midpoint(self) -> float:
        return self.start + self.duration / 2.0


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def find_ffmpeg(explicit: Optional[str]) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_ffmpeg = os.environ.get("FFMPEG")
    if env_ffmpeg:
        candidates.append(env_ffmpeg)
    candidates.extend(DEFAULT_FFMPEG_CANDIDATES)
    for item in candidates:
        found = shutil.which(item) if os.path.basename(item) == item else item
        if found and Path(found).exists() and os.access(found, os.X_OK):
            return found
    raise SystemExit(
        "ffmpeg not found. Install ffmpeg or pass --ffmpeg /path/to/ffmpeg. "
        "This repo can use .video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1."
    )


def run(cmd: List[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )


def probe_duration(ffmpeg: str, video: Path) -> float:
    proc = run([ffmpeg, "-hide_banner", "-i", str(video)])
    text = (proc.stderr or b"").decode("utf-8", errors="ignore")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def load_config(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Config must be a JSON object.")
    return data


def resolve_thresholds(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(config.get("thresholds") or {})
    for key in DEFAULT_THRESHOLDS:
        arg_value = getattr(args, key)
        if arg_value is not None:
            thresholds[key] = arg_value
        thresholds[key] = float(thresholds[key])
    return thresholds


def build_shots(config: Dict[str, Any], duration: float) -> List[Shot]:
    raw_shots = config.get("shots") or []
    if not raw_shots:
        sample_count = int(config.get("auto_sample_count", 18))
        step = duration / max(1, sample_count)
        raw_shots = [
            {"shot_id": f"{idx + 1:02d}", "start": idx * step, "end": (idx + 1) * step}
            for idx in range(sample_count)
        ]

    shots: List[Shot] = []
    cursor = 0.0
    for idx, raw in enumerate(raw_shots):
        shot_id = str(raw.get("shot_id") or raw.get("id") or f"{idx + 1:02d}")
        if "start" in raw and "end" in raw:
            start = float(raw["start"])
            end = float(raw["end"])
        else:
            dur = float(raw.get("duration", raw.get("seconds", 8)))
            start = cursor
            end = start + dur
            cursor = end
        shots.append(
            Shot(
                shot_id=shot_id,
                start=max(0.0, start),
                end=max(0.0, end),
                title=str(raw.get("title", "")),
                scene_id=str(raw.get("scene_id", "")),
                scene_group_id=str(raw.get("scene_group_id", "")),
                room_id=str(raw.get("room_id", "")),
                zone_id=str(raw.get("zone_id", "")),
                angle_id=str(raw.get("angle_id", "")),
                characters=list(raw.get("characters", [])),
                props=list(raw.get("props", [])),
                dialogue=str(raw.get("dialogue", "")),
                repair_prompt=str(raw.get("repair_prompt", "")),
                repair_stage=str(raw.get("repair_stage", "storyboard")),
                notes=str(raw.get("notes", "")),
            )
        )
    return shots


def extract_jpeg(ffmpeg: str, video: Path, timestamp: float, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, timestamp):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-y",
        str(out_path),
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", errors="ignore"))


def raw_ppm_frame(ffmpeg: str, video: Path, timestamp: float, size: int = 48) -> Tuple[int, int, bytes]:
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, timestamp):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale={size}:{size}:force_original_aspect_ratio=decrease,pad={size}:{size}:(ow-iw)/2:(oh-ih)/2",
        "-f",
        "image2pipe",
        "-vcodec",
        "ppm",
        "-",
    ]
    proc = run(cmd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", errors="ignore"))
    data = proc.stdout or b""
    match = re.match(rb"P6\s+(\d+)\s+(\d+)\s+255\s", data)
    if not match:
        raise RuntimeError("Unable to parse ffmpeg PPM frame.")
    width = int(match.group(1))
    height = int(match.group(2))
    header_len = match.end()
    return width, height, data[header_len:]


def fingerprint(ffmpeg: str, video: Path, timestamp: float) -> Dict[str, Any]:
    width, height, rgb = raw_ppm_frame(ffmpeg, video, timestamp, size=48)
    pixels = [rgb[i : i + 3] for i in range(0, len(rgb), 3)]
    if not pixels:
        return {"ahash": "", "hist": [], "mean_rgb": [0, 0, 0], "brightness": 0}

    grays = []
    hist = [0] * 64
    r_total = g_total = b_total = 0
    for pix in pixels:
        r, g, b = pix[0], pix[1], pix[2]
        r_total += r
        g_total += g
        b_total += b
        gray = int(0.299 * r + 0.587 * g + 0.114 * b)
        grays.append(gray)
        rb = min(3, r // 64)
        gb = min(3, g // 64)
        bb = min(3, b // 64)
        hist[rb * 16 + gb * 4 + bb] += 1
    total = max(1, len(pixels))
    hist_norm = [v / total for v in hist]
    mean_rgb = [r_total / total, g_total / total, b_total / total]

    # Average hash on the downscaled frame.
    avg = sum(grays) / len(grays)
    bits = ["1" if gray >= avg else "0" for gray in grays]
    bit_string = "".join(bits)
    encoded = hex(int(bit_string, 2))[2:].zfill(math.ceil(len(bit_string) / 4))
    return {
        "ahash": encoded,
        "hist": hist_norm,
        "mean_rgb": mean_rgb,
        "brightness": sum(grays) / len(grays),
        "width": width,
        "height": height,
    }


def hamming_hex(a: str, b: str) -> int:
    if not a or not b:
        return 0
    size = max(len(a), len(b))
    av = int(a.zfill(size), 16)
    bv = int(b.zfill(size), 16)
    return bin(av ^ bv).count("1")


def hist_distance(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b)) / 2.0


def rgb_distance(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))) / 441.67295593


def pair_score(fp_a: Dict[str, Any], fp_b: Dict[str, Any]) -> Dict[str, float]:
    hash_bits = len(fp_a.get("ahash", "")) * 4 or 1
    ahash = hamming_hex(fp_a.get("ahash", ""), fp_b.get("ahash", "")) / hash_bits
    hist = hist_distance(fp_a.get("hist", []), fp_b.get("hist", []))
    rgb = rgb_distance(fp_a.get("mean_rgb", []), fp_b.get("mean_rgb", []))
    combined = 0.45 * ahash + 0.40 * hist + 0.15 * rgb
    return {"combined": combined, "ahash": ahash, "hist": hist, "rgb": rgb}


def group_key(shot: Shot, kind: str) -> List[str]:
    if kind == "scene":
        return [shot.scene_group_id or shot.room_id or shot.scene_id]
    if kind == "character":
        return shot.characters
    if kind == "prop":
        return shot.props
    return []


def issue_severity(score: float, warn: float, fail: float) -> str:
    if score >= fail:
        return "fail"
    if score >= warn:
        return "warn"
    return "pass"


def create_pair_issues(
    shots: List[Shot],
    frame_data: Dict[str, Dict[str, Any]],
    *,
    kind: str,
    warn: float,
    fail: float,
    min_group_size: int = 2,
) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Shot]] = {}
    for shot in shots:
        for key in group_key(shot, kind):
            if key:
                groups.setdefault(key, []).append(shot)

    issues: List[Dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        if len(group) < min_group_size:
            continue
        pairs = []
        for idx, a in enumerate(group):
            for b in group[idx + 1 :]:
                fa = frame_data[a.shot_id]["fingerprint"]
                fb = frame_data[b.shot_id]["fingerprint"]
                score = pair_score(fa, fb)
                severity = issue_severity(score["combined"], warn, fail)
                if severity != "pass":
                    pairs.append((a, b, score, severity))
        if not pairs:
            continue

        worst = max(pairs, key=lambda item: item[2]["combined"])
        bad_shots = sorted({shot.shot_id for pair in pairs for shot in (pair[0], pair[1])})
        issue_type = {
            "scene": "scene_room_continuity",
            "character": "character_visual_drift",
            "prop": "prop_visual_drift",
        }[kind]
        issues.append(
            {
                "type": issue_type,
                "severity": worst[3],
                "anchor_id": key,
                "shot_ids": bad_shots,
                "worst_pair": [worst[0].shot_id, worst[1].shot_id],
                "score": {k: round(v, 4) for k, v in worst[2].items()},
                "evidence": [
                    frame_data[worst[0].shot_id]["frame_path"],
                    frame_data[worst[1].shot_id]["frame_path"],
                ],
                "diagnosis": diagnosis_for(kind, key, bad_shots, worst[2]["combined"]),
                "repair_stage": "storyboard" if kind == "scene" else "storyboard_or_material",
                "repair_action": repair_action_for(kind),
            }
        )
    return issues


def diagnosis_for(kind: str, key: str, shot_ids: List[str], score: float) -> str:
    if kind == "scene":
        return (
            f"{key} 在镜头 {', '.join(shot_ids)} 之间视觉差异过大"
            f"（漂移分 {score:.2f}），按同一房间连续性风险处理。"
        )
    if kind == "character":
        return (
            f"{key} 在镜头 {', '.join(shot_ids)} 之间视觉漂移偏高。"
            "检查脸型、体态、服装，以及是否误生成成另一个角色。"
        )
    return (
        f"{key} 在镜头 {', '.join(shot_ids)} 之间视觉漂移偏高。"
        "检查道具外形、摆放位置、可读文字和镜头交接关系。"
    )


def repair_action_for(kind: str) -> str:
    if kind == "scene":
        return (
            "回到故事板/素材源，锁定 ROOM-ID、ZONE-ID、ANGLE-ID，"
            "再重生受影响分镜视频。只有 UI 无法创建任务时才走 API 兜底。"
        )
    if kind == "character":
        return (
            "对照角色库检查受影响镜头，先修素材/故事板参考图，再重生分镜视频。"
        )
    return (
        "先修故事板道具帧或素材道具卡，再重生分镜视频。不能靠字幕或旁白修。"
    )


def compose_repair_prompt(shot: Shot, config: Dict[str, Any]) -> str:
    if shot.repair_prompt:
        return shot.repair_prompt
    scene_note = config.get("scene_anchors", {}).get(shot.room_id or shot.scene_id, "")
    parts = [
        scene_note,
        f"镜头 {shot.shot_id}：{shot.title}".strip(),
        f"场景锚点：{shot.scene_id}",
        f"房间锚点：{shot.room_id}",
        f"区域锚点：{shot.zone_id}",
        f"机位锚点：{shot.angle_id}",
        f"出场角色：{'、'.join(shot.characters)}",
        f"关键道具：{'、'.join(shot.props)}",
    ]
    if shot.dialogue:
        dialogue = shot.dialogue.rstrip("。.!！?？；;，, ")
        parts.append(f"普通话对白：{dialogue}。本镜头只说完这一句台词，说完后停顿半秒，口型同步。")
    parts.append(
        "生成真人动作视频，竖屏9:16，720p，华语现实短剧电影质感。保持同一房间布局、门窗、病床、床头柜、床帘、监护仪、道具位置和人物站位连续。人物为中国或东亚面孔，镜头有明确动作推进和自然环境声。"
    )
    return "\n".join([part for part in parts if part and not part.endswith(": ")])


def platform_action_for(issue_type: str, shot: Shot) -> str:
    if issue_type == "scene_room_continuity":
        return (
            f"回到 Giggle `故事板` 第 {shot.shot_id} 镜，先修对应素材/故事板图；锁定 "
            f"{shot.room_id or shot.scene_id} / {shot.zone_id} / {shot.angle_id}，再到 `分镜` 单镜重生视频。"
        )
    if issue_type == "character_visual_drift":
        return (
            f"回到第 {shot.shot_id} 镜的角色素材与故事板图，对照角色库重建参考图，再单镜重生视频。"
        )
    return f"回到第 {shot.shot_id} 镜的道具素材或故事板图，固定道具外形与位置，再单镜重生视频。"


def api_payload_draft_for(shot: Shot, prompt: str) -> Dict[str, Any]:
    return {
        "auth": "Authorization: Bearer <GIGGLE_API_KEY>",
        "model_priority": ["seedance-2.0-pro", "veo3.1", "sora2", "wan2.7", "kling"],
        "ratio": "9:16",
        "resolution": "720p",
        "duration_seconds": round(shot.duration, 2),
        "reference_image": f"<upload repaired source image for shot {shot.shot_id}>",
        "prompt": prompt,
        "audio_requirement": "使用平台视频模型同步生成普通话对白、口型、环境声；不得用本地后配音作为最终交付。",
    }


def build_repair_plan(
    config: Dict[str, Any],
    video: Path,
    shots: List[Shot],
    frame_data: Dict[str, Dict[str, Any]],
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    by_id = {shot.shot_id: shot for shot in shots}
    severity_rank = {"pass": 0, "warn": 1, "fail": 2}
    tasks_by_shot: Dict[str, Dict[str, Any]] = {}
    for issue in issues:
        for sid in issue["shot_ids"]:
            shot = by_id.get(sid)
            if not shot:
                continue
            prompt = compose_repair_prompt(shot, config)
            task = tasks_by_shot.get(sid)
            if not task:
                task = {
                    "episode_id": config.get("episode_id", video.stem),
                    "video": str(video),
                    "primary_issue_type": issue["type"],
                    "severity": issue["severity"],
                    "shot_id": shot.shot_id,
                    "title": shot.title,
                    "time_range_seconds": [round(shot.start, 2), round(shot.end, 2)],
                    "duration_seconds": round(shot.duration, 2),
                    "scene_id": shot.scene_id,
                    "scene_group_id": shot.scene_group_id,
                    "room_id": shot.room_id,
                    "zone_id": shot.zone_id,
                    "angle_id": shot.angle_id,
                    "characters": shot.characters,
                    "props": shot.props,
                    "dialogue": shot.dialogue,
                    "evidence_frame": frame_data[shot.shot_id]["frame_path"],
                    "source_issues": [],
                    "repair_stage": shot.repair_stage or issue["repair_stage"],
                    "platform_action": platform_action_for(issue["type"], shot),
                    "api_fallback_payload_draft": api_payload_draft_for(shot, prompt),
                    "prompt": prompt,
                    "acceptance_checks": [
                        "同一 ROOM-ID 的门窗、床、床头柜、床帘、监护仪、墙面色温连续。",
                        "出场角色脸型、发型、服装、体态与角色库一致。",
                        "本镜头对白为中文普通话，台词完整说完，口型同步。",
                        "镜头不是静态故事板图，有事件动作推进和可听环境声。",
                    ],
                }
                tasks_by_shot[sid] = task
            if severity_rank[issue["severity"]] > severity_rank[task["severity"]]:
                task["severity"] = issue["severity"]
                task["primary_issue_type"] = issue["type"]
                task["platform_action"] = platform_action_for(issue["type"], shot)
            task["source_issues"].append(
                {
                    "issue_type": issue["type"],
                    "severity": issue["severity"],
                    "anchor_id": issue["anchor_id"],
                    "score": issue["score"],
                    "worst_pair": issue["worst_pair"],
                    "evidence": issue["evidence"],
                }
            )
    tasks = [tasks_by_shot[sid] for sid in sorted(tasks_by_shot)]
    return {
        "episode_id": config.get("episode_id", video.stem),
        "video": str(video),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "repair_task_count": len(tasks),
        "tasks": tasks,
    }


def write_reports(
    out_dir: Path,
    config: Dict[str, Any],
    video: Path,
    shots: List[Shot],
    frame_data: Dict[str, Dict[str, Any]],
    issues: List[Dict[str, Any]],
    thresholds: Dict[str, float],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "episode_id": config.get("episode_id", video.stem),
        "video": str(video),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "issue_count": len(issues),
        "fail_count": sum(1 for item in issues if item["severity"] == "fail"),
        "warn_count": sum(1 for item in issues if item["severity"] == "warn"),
        "thresholds": thresholds,
        "shots": [
            {
                **dataclasses.asdict(shot),
                "frame_path": frame_data[shot.shot_id]["frame_path"],
                "fingerprint": {
                    "mean_rgb": [round(x, 2) for x in frame_data[shot.shot_id]["fingerprint"]["mean_rgb"]],
                    "brightness": round(frame_data[shot.shot_id]["fingerprint"]["brightness"], 2),
                },
            }
            for shot in shots
        ],
        "issues": issues,
    }
    (out_dir / "continuity_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(out_dir / "continuity_report.md", report, shots, frame_data, config)
    write_html(out_dir / "contact_sheet.html", report, shots, frame_data)
    write_repair_prompts(out_dir / "repair_prompts.md", issues, shots, config)
    repair_plan = build_repair_plan(config, video, shots, frame_data, issues)
    (out_dir / "repair_plan.json").write_text(
        json.dumps(repair_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_markdown(
    path: Path,
    report: Dict[str, Any],
    shots: List[Shot],
    frame_data: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> None:
    lines = [
        f"# Continuity Audit: {report['episode_id']}",
        "",
        f"- Video: `{report['video']}`",
        f"- Created: `{report['created_at']}`",
        f"- Issues: `{report['issue_count']}` (`fail`: {report['fail_count']}, `warn`: {report['warn_count']})",
        "- Repair plan: `repair_plan.json`",
        "",
        "## Blocking Issues",
        "",
    ]
    if not report["issues"]:
        lines.append("No visual continuity issues crossed the configured thresholds.")
    else:
        for idx, issue in enumerate(report["issues"], 1):
            lines.extend(
                [
                    f"### {idx}. {issue['type']} / {issue['severity']} / {issue['anchor_id']}",
                    "",
                    f"- Shots: `{', '.join(issue['shot_ids'])}`",
                    f"- Worst pair: `{issue['worst_pair'][0]}` vs `{issue['worst_pair'][1]}`",
                    f"- Score: `{issue['score']}`",
                    f"- Diagnosis: {issue['diagnosis']}",
                    f"- Repair stage: `{issue['repair_stage']}`",
                    f"- Repair action: {issue['repair_action']}",
                    f"- Evidence: `{issue['evidence'][0]}`, `{issue['evidence'][1]}`",
                    "",
                ]
            )
    lines.extend(["## Shot Frames", ""])
    for shot in shots:
        rel = Path(frame_data[shot.shot_id]["frame_path"]).name
        lines.append(
            f"- `{shot.shot_id}` {shot.title} "
            f"`{shot.room_id or shot.scene_id}` `{shot.zone_id}` `{shot.angle_id}` "
            f"![{shot.shot_id}](frames/{rel})"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(path: Path, report: Dict[str, Any], shots: List[Shot], frame_data: Dict[str, Dict[str, Any]]) -> None:
    cards = []
    issue_shots = {sid for issue in report["issues"] for sid in issue["shot_ids"]}
    for shot in shots:
        rel = "frames/" + Path(frame_data[shot.shot_id]["frame_path"]).name
        cls = "issue" if shot.shot_id in issue_shots else "ok"
        cards.append(
            f"""
            <article class="{cls}">
              <img src="{html.escape(rel)}" alt="shot {html.escape(shot.shot_id)}">
              <h3>{html.escape(shot.shot_id)} {html.escape(shot.title)}</h3>
              <p><b>Room:</b> {html.escape(shot.room_id or shot.scene_id)}</p>
              <p><b>Zone:</b> {html.escape(shot.zone_id)} | <b>Angle:</b> {html.escape(shot.angle_id)}</p>
              <p><b>Chars:</b> {html.escape(', '.join(shot.characters))}</p>
              <p><b>Props:</b> {html.escape(', '.join(shot.props))}</p>
            </article>
            """
        )
    body = f"""
    <!doctype html>
    <html lang="zh-CN">
    <meta charset="utf-8">
    <title>Continuity Audit {html.escape(str(report['episode_id']))}</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#101114; color:#f3f3f3; margin:24px; }}
      .summary {{ margin-bottom: 20px; }}
      .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:14px; }}
      article {{ border:1px solid #333; border-radius:8px; padding:10px; background:#191b20; }}
      article.issue {{ border-color:#ff6b6b; box-shadow:0 0 0 1px #ff6b6b inset; }}
      img {{ width:100%; border-radius:4px; background:#000; }}
      h3 {{ margin:8px 0; font-size:16px; }}
      p {{ margin:4px 0; color:#c9c9c9; font-size:13px; }}
    </style>
    <body>
      <section class="summary">
        <h1>Continuity Audit: {html.escape(str(report['episode_id']))}</h1>
        <p>Issues: {report['issue_count']} / fail {report['fail_count']} / warn {report['warn_count']}</p>
      </section>
      <section class="grid">
        {''.join(cards)}
      </section>
    </body>
    </html>
    """
    path.write_text(body, encoding="utf-8")


def write_repair_prompts(path: Path, issues: List[Dict[str, Any]], shots: List[Shot], config: Dict[str, Any]) -> None:
    by_id = {shot.shot_id: shot for shot in shots}
    affected = []
    for issue in issues:
        for sid in issue["shot_ids"]:
            if sid not in affected:
                affected.append(sid)
    lines = [
        "# 返修提示词",
        "",
        "优先用于 Giggle `故事板` 逐镜返修。若 UI 无法创建任务或参考图上传失败，再用同一提示词和源帧走官方 API 兜底。",
        "",
    ]
    if not affected:
        lines.append("没有触发阈值的问题，因此未生成返修提示词。")
    for sid in affected:
        shot = by_id[sid]
        lines.extend(
            [
                f"## 镜头 {sid}：{shot.title}",
                "",
                f"- 建议返修阶段：`{shot.repair_stage}`",
                f"- 房间/场景：`{shot.room_id or shot.scene_id}`",
                f"- 区域：`{shot.zone_id}`",
                f"- 机位：`{shot.angle_id}`",
                "",
                "```text",
                compose_repair_prompt(shot, config),
                "```",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Audit short-drama scene/person/prop continuity from local MP4.")
    parser.add_argument("--video", required=True, help="Episode MP4 path.")
    parser.add_argument("--config", required=True, help="Episode continuity JSON config.")
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--ffmpeg", help="ffmpeg binary path.")
    parser.add_argument("--scene-warn", type=float)
    parser.add_argument("--scene-fail", type=float)
    parser.add_argument("--character-warn", type=float)
    parser.add_argument("--character-fail", type=float)
    parser.add_argument("--prop-warn", type=float)
    parser.add_argument("--prop-fail", type=float)
    parser.add_argument("--fail-on-issues", action="store_true")
    args = parser.parse_args(argv)

    video = Path(args.video).expanduser().resolve()
    config_path = Path(args.config).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    ffmpeg = find_ffmpeg(args.ffmpeg)
    config = load_config(config_path)
    thresholds = resolve_thresholds(config, args)
    duration = probe_duration(ffmpeg, video)
    shots = build_shots(config, duration)

    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_data: Dict[str, Dict[str, Any]] = {}
    for shot in shots:
        ts = min(max(shot.midpoint, 0.0), max(0.0, duration - 0.1)) if duration else shot.midpoint
        frame_path = frames_dir / f"shot_{shot.shot_id}_{ts:07.2f}s.jpg"
        extract_jpeg(ffmpeg, video, ts, frame_path)
        frame_data[shot.shot_id] = {
            "timestamp": ts,
            "frame_path": str(frame_path),
            "fingerprint": fingerprint(ffmpeg, video, ts),
        }

    issues: List[Dict[str, Any]] = []
    issues.extend(
        create_pair_issues(
            shots,
            frame_data,
            kind="scene",
            warn=thresholds["scene_warn"],
            fail=thresholds["scene_fail"],
        )
    )
    issues.extend(
        create_pair_issues(
            shots,
            frame_data,
            kind="character",
            warn=thresholds["character_warn"],
            fail=thresholds["character_fail"],
        )
    )
    issues.extend(
        create_pair_issues(
            shots,
            frame_data,
            kind="prop",
            warn=thresholds["prop_warn"],
            fail=thresholds["prop_fail"],
        )
    )
    issues.sort(key=lambda item: (0 if item["severity"] == "fail" else 1, item["type"], item["anchor_id"]))

    write_reports(out_dir, config, video, shots, frame_data, issues, thresholds)

    print(f"continuity_report={out_dir / 'continuity_report.md'}")
    print(f"contact_sheet={out_dir / 'contact_sheet.html'}")
    print(f"repair_prompts={out_dir / 'repair_prompts.md'}")
    print(f"repair_plan={out_dir / 'repair_plan.json'}")
    print(f"issues={len(issues)} fail={sum(1 for item in issues if item['severity'] == 'fail')}")
    if args.fail_on_issues and any(item["severity"] == "fail" for item in issues):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
